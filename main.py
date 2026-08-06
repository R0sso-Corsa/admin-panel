import os
import secrets
import subprocess
import json
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
        running, _ = docker_cmd("ps", "-q", "-f", f"name={svc['container']}")
        result[name] = {**svc, "running": running}
    return JSONResponse(result)


@app.post("/api/services/{name}/toggle")
async def toggle_service(name: str, request: Request):
    require_auth(request)
    services = load_services()
    if name not in services:
        raise HTTPException(status_code=404, detail="Service not found")
    svc = services[name]
    running, _ = docker_cmd("ps", "-q", "-f", f"name={svc['container']}")
    if running:
        success, out = docker_cmd("stop", svc["container"])
        action = "stop"
    else:
        success, out = docker_cmd("start", svc["container"])
        action = "start"
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to {action}: {out}")
    running_after, _ = docker_cmd("ps", "-q", "-f", f"name={svc['container']}")
    return JSONResponse({"ok": True, "running": bool(running_after)})


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
        r, _ = docker_cmd("ps", "-q", "-f", f"name={svc['container']}")
        if r:
            running += 1
    # Get uptime
    try:
        import subprocess
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
    
    containers = [svc['container'] for name, svc in services.items() 
                  if not service_name or name == service_name]
    
    all_logs = []
    for container in containers:
        success, out = docker_cmd("logs", "--tail", str(lines), container)
        if success and out:
            for line in out.strip().split('\n'):
                all_logs.append({"time": "", "text": line, "service": container})
    
    # Sort by time (newest first)
    all_logs.sort(key=lambda x: x["time"], reverse=True)
    return JSONResponse({"logs": all_logs[:lines]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
