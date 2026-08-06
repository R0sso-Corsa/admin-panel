import os
import secrets
import subprocess
import json
import time
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
SERVICES_DIR = BASE_DIR / "services"
TOKEN_FILE = BASE_DIR / ".token"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-in-production")
SESSION_COOKIE = "admin_session"

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

SERVICES_DIR.mkdir(exist_ok=True)


def load_services() -> dict:
    services = {}
    for path in SERVICES_DIR.glob("*.json"):
        try:
            services[path.stem] = json.loads(path.read_text())
        except Exception:
            continue
    return services


def save_service(name: str, data: dict):
    (SERVICES_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))


def docker_cmd(*args: str) -> tuple[bool, str]:
    cmd = ["docker"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip()
    except Exception as exc:
        return False, str(exc)


def container_running(container_name: str) -> bool:
    success, out = docker_cmd("ps", "-q", "-f", f"name={container_name}")
    if not success or not out:
        return False
    success2, out2 = docker_cmd("ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}|{{.Status}}")
    if not success2 or not out2:
        return False
    for line in out2.strip().split("\n"):
        if line.startswith(f"{container_name}|") and line.split("|", 1)[1].startswith("Up"):
            return True
    return False


def read_pid_file(path: str) -> int | None:
    try:
        text = Path(path).read_text().strip()
        if text:
            return int(text)
    except Exception:
        pass
    return None


def discover_pid_by_cmd(cmd_substring: str) -> int | None:
    try:
        out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True, timeout=10).stdout.strip()
        for line in out.split("\n")[1:]:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and cmd_substring in parts[1]:
                return int(parts[0])
    except Exception:
        pass
    return None


def process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it; treat as running
        return True
    except Exception:
        return False


def start_process(service: dict) -> bool:
    cmd = service.get("command", "")
    cwd = service.get("working_dir", "/home/vps")
    pid_file = service.get("pid_file")
    if not cmd:
        return False
    # Check if already running using stored PID or discovered PID
    existing_pid = read_pid_file(pid_file) if pid_file else None
    if existing_pid is not None and process_running(existing_pid):
        return True
    if pid_file:
        Path(pid_file).unlink(missing_ok=True)
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if pid_file:
            Path(pid_file).write_text(str(proc.pid))
        return True
    except Exception:
        return False


def stop_process(service: dict) -> bool:
    pid = None
    pid_file = service.get("pid_file")
    if pid_file:
        pid = read_pid_file(pid_file)
    if pid is None:
        pid = discover_pid_by_cmd(service.get("command", "").split()[0] if service.get("command") else "")
    if pid is None:
        return True
    try:
        os.kill(pid, 15)
        for _ in range(10):
            if not process_running(pid):
                return True
            time.sleep(0.5)
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def service_running(service: dict) -> bool:
    kind = service.get("kind", "docker")
    if kind == "process":
        pid_file = service.get("pid_file")
        pid = read_pid_file(pid_file) if pid_file else None
        if pid is None and service.get("command"):
            pid = discover_pid_by_cmd(service.get("command", "").split()[0])
        if pid is not None and process_running(pid):
            if pid_file:
                try:
                    Path(pid_file).write_text(str(pid))
                except Exception:
                    pass
            return True
        return False
    return container_running(service.get("container", ""))


def start_service_cmd(service: dict) -> bool:
    kind = service.get("kind", "docker")
    if kind == "process":
        return start_process(service)
    success, _ = docker_cmd("start", service["container"])
    return success


def stop_service_cmd(service: dict) -> bool:
    kind = service.get("kind", "docker")
    if kind == "process":
        return stop_process(service)
    success, _ = docker_cmd("stop", service["container"])
    return success


def service_logs(service: dict, lines: int = 100) -> list[dict]:
    kind = service.get("kind", "docker")
    log_file = service.get("log_file")
    if kind == "process" and log_file:
        try:
            text = Path(log_file).read_text(errors="ignore")
            rows = text.splitlines()
            rows = [r for r in rows if r.strip()]
            rows = rows[-lines:]
            return [{"time": "", "text": line, "service": service.get("name", "")} for line in rows]
        except Exception:
            return []
    container = service.get("container", "")
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        out = result.stdout.strip()
        if not out:
            return []
        return [{"time": "", "text": line, "service": container} for line in out.split("\n") if line.strip()]
    except Exception:
        return []


def get_session(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def require_auth(request: Request) -> str:
    token = get_session(request)
    if not token or not TOKEN_FILE.exists() or TOKEN_FILE.read_text().strip() != token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


@app.get("/", response_class=HTMLResponse)
async def login(request: Request):
    token = get_session(request)
    if token and TOKEN_FILE.exists() and TOKEN_FILE.read_text().strip() == token:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def do_login(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400, samesite="lax")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    require_auth(request)
    services = load_services()
    return templates.TemplateResponse("dashboard.html", {"request": request, "services": services})


@app.get("/api/services")
async def api_services(request: Request):
    require_auth(request)
    services = load_services()
    result = {}
    for name, svc in services.items():
        result[name] = {**svc, "running": service_running(svc)}
    return JSONResponse(result)


@app.post("/api/services/{name}/toggle")
async def toggle_service(name: str, request: Request):
    require_auth(request)
    services = load_services()
    if name not in services:
        raise HTTPException(status_code=404, detail="Service not found")
    svc = services[name]
    was_running = service_running(svc)
    if was_running:
        success = stop_service_cmd(svc)
        action = "stop"
    else:
        success = start_service_cmd(svc)
        action = "start"
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to {action}")
    return JSONResponse({"ok": True, "running": service_running(svc)})


@app.post("/api/services")
async def create_service(request: Request, name: str = Form(...), container: str = Form(...)):
    require_auth(request)
    if not name or not container:
        raise HTTPException(status_code=400, detail="Missing fields")
    save_service(name, {"container": container, "running": False})
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/services/{name}/delete")
async def delete_service(name: str, request: Request):
    require_auth(request)
    path = SERVICES_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/logout")
async def logout():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/stats")
async def api_stats(request: Request):
    require_auth(request)
    services = load_services()
    running = 0
    for svc in services.values():
        if service_running(svc):
            running += 1
    # Get uptime
    try:
        uptime_out = subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip()
    except Exception:
        uptime_out = "Unknown"
    return JSONResponse({"running": running, "total": len(services), "uptime": uptime_out})


@app.get("/api/system")
async def api_system(request: Request):
    require_auth(request)
    stats = {
        "cpu": "N/A",
        "memory": "N/A",
        "disk": "N/A",
        "containers": {"total": 0, "running": 0},
    }
    # CPU
    try:
        with open("/proc/loadavg") as f:
            stats["cpu"] = f.read().strip().split()[0]
    except Exception:
        pass
    # Memory
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {}
        for line in lines[:5]:
            parts = line.split()
            mem[parts[0].rstrip(":")] = int(parts[1])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used = total - avail
        stats["memory"] = {
            "used_mb": round(used / 1024),
            "total_mb": round(total / 1024),
            "percent": round((used / total) * 100) if total else 0,
        }
    except Exception:
        pass
    # Disk
    try:
        import shutil
        usage = shutil.disk_usage("/")
        stats["disk"] = {
            "used_gb": round(usage.used / (1024**3), 1),
            "total_gb": round(usage.total / (1024**3), 1),
            "percent": round((usage.used / usage.total) * 100),
        }
    except Exception:
        pass
    # Containers
    success, out = docker_cmd("ps", "-a", "--format", "{{.Names}}|{{.Status}}")
    if success and out:
        stats["containers"]["total"] = len(out.strip().split("\n"))
        stats["containers"]["running"] = sum(1 for line in out.strip().split("\n") if "Up" in line)
    return JSONResponse(stats)


@app.post("/api/services/{name}/restart")
async def restart_service(name: str, request: Request):
    require_auth(request)
    services = load_services()
    if name not in services:
        raise HTTPException(status_code=404, detail="Service not found")
    svc = services[name]
    success, out = docker_cmd("restart", svc["container"])
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to restart: {out}")
    return JSONResponse({"ok": True, "running": True})


@app.get("/api/logs")
@app.get("/api/logs/{service_name}")
async def api_logs(request: Request, service_name: str = None, lines: int = 100):
    require_auth(request)
    services = load_services()

    if service_name and service_name not in services:
        raise HTTPException(status_code=404, detail="Service not found")

    target_names = [service_name] if service_name else list(services.keys())
    all_logs = []
    for name in target_names:
        svc = services.get(name, {})
        logs = service_logs(svc, lines=lines)
        all_logs.extend(logs)

    all_logs.sort(key=lambda x: x.get("time", ""), reverse=True)
    return JSONResponse({"logs": all_logs[:lines]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
