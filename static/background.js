import * as THREE from '/static/three/three.module.js';
document.documentElement.style.setProperty('--glass-filter', 'url(#liquid-glass-admin)');

const canvas = document.getElementById('bg-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
camera.position.z = 1;

const bgGeo = new THREE.PlaneGeometry(2, 2);
const bgMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) } },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `
        varying vec2 vUv; uniform float uTime; uniform vec2 uResolution;
        vec3 mod289(vec3 x){return x - floor(x*(1.0/289.0))*289.0;}
        vec4 mod289(vec4 x){return x - floor(x*(1.0/289.0))*289.0;}
        vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
        vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314*r;}
        float snoise(vec3 v){ const vec2 C = vec2(1.0/6.0, 1.0/3.0); const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
            vec3 i = floor(v + dot(v, C.yyy)); vec3 x0 = v - i + dot(i, C.xxx); vec3 g = step(x0.yzx, x0.xyz); vec3 l = 1.0 - g;
            vec3 i1 = min(g.xyz, l.zxy); vec3 i2 = max(g.xyz, l.zxy); vec3 x1 = x0 - i1 + C.xxx; vec3 x2 = x0 - i2 + C.yyy; vec3 x3 = x0 - D.yyy;
            i = mod289(i); vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
            float n_ = 0.142857142857; vec3 ns = n_ * D.wyz - D.xzx; vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
            vec4 x_ = floor(j * ns.z); vec4 y_ = floor(j - 7.0 * x_); vec4 x = x_ *ns.x + ns.yyyy; vec4 y = y_ *ns.x + ns.yyyy;
            vec4 h = 1.0 - abs(x) - abs(y); vec4 b0 = vec4(x.xy, y.xy); vec4 b1 = vec4(x.zw, y.zw);
            vec4 s0 = floor(b0)*2.0 + 1.0; vec4 s1 = floor(b1)*2.0 + 1.0; vec4 sh = -step(h, vec4(0.0));
            vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy; vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
            vec3 p0 = vec3(a0.xy,h.x); vec3 p1 = vec3(a0.zw,h.y); vec3 p2 = vec3(a1.xy,h.z); vec3 p3 = vec3(a1.zw,h.w);
            vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
            p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
            vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0); m = m * m;
            return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
        }
        float fbm(vec3 p){ float val = 0.0; float amp = 0.5; float freq = 1.0; for(int i=0; i<6; i++){ val += amp * snoise(p * freq); freq *= 2.1; amp *= 0.48; } return val; }
        float warpedNoise(vec2 st, float t){ vec3 p = vec3(st, t); float wx = fbm(p + vec3(0.0, 1.7, 0.3)); float wy = fbm(p + vec3(1.5, 0.0, 2.1)); return fbm(vec3(st + vec2(wx, wy) * 0.55, t)); }
        void main(){
            vec2 st = (vUv-0.5)*vec2(uResolution.x/uResolution.y,1.0); float t = uTime * 0.012;
            float n1 = warpedNoise(st * 1.4, t); float n2 = warpedNoise(st * 2.8 + 3.7, t * 0.7);
            float v1 = (n1 + 1.0) * 0.5; float v2 = (n2 + 1.0) * 0.5;
            float bands1 = 8.0; float bands2 = 12.0; float r1 = ceil(v1 * bands1); float r2 = ceil(v2 * bands2);
            float edge1 = abs((r1 / bands1) - v1); float edge2 = abs((r2 / bands2) - v2);
            float line1 = 1.0 - smoothstep(0.0, 0.045, edge1); float line2 = 1.0 - smoothstep(0.0, 0.035, edge2);
            float line = max(line1, line2 * 0.35); float depth = 1.0 - smoothstep(0.0, 0.9, length(st));
            vec3 lineBright = vec3(0.30, 0.30, 0.34); vec3 lineDim = vec3(0.14, 0.14, 0.17);
            vec3 fg = mix(lineDim, lineBright, depth * 0.7 + 0.3); vec3 col = mix(vec3(0.0), fg, line);
            gl_FragColor = vec4(col, 1.0);
        }
    `
});
const bgQuad = new THREE.Mesh(bgGeo, bgMat);
scene.add(bgQuad);
function animate(time) { requestAnimationFrame(animate); bgMat.uniforms.uTime.value = time * 0.001; renderer.render(scene, camera); }
requestAnimationFrame(animate);
window.addEventListener('resize', () => { renderer.setSize(window.innerWidth, window.innerHeight); bgMat.uniforms.uResolution.value.set(window.innerWidth, window.innerHeight); });

// CARD TILT
const cards = Array.from(document.querySelectorAll('.glass-card'));
const target = cards.map(() => ({ rx: 0, ry: 0, scale: 1, glow: 0 }));
const current = cards.map(() => ({ rx: 0, ry: 0, scale: 1, glow: 0 }));
let viewportCX = window.innerWidth / 2, viewportCY = window.innerHeight / 2, cursorX = viewportCX, cursorY = viewportCY;
document.addEventListener('mousemove', e => { cursorX = e.clientX; cursorY = e.clientY; });
window.addEventListener('resize', () => { viewportCX = window.innerWidth / 2; viewportCY = window.innerHeight / 2; });
function updateCardTargets() {
    const dx = (cursorX - viewportCX) / (viewportCX || 1); const dy = (cursorY - viewportCY) / (viewportCY || 1);
    const dist = Math.min(1, Math.sqrt(dx * dx + dy * dy)); const influence = Math.min(1, dist * 1.1);
    cards.forEach((card, i) => {
        target[i].rx = -dy * 0.45 * influence; target[i].ry = dx * 0.45 * influence;
        target[i].scale = 1 + dist * 0.04; target[i].glow = dist * 0.8;
        const rect = card.getBoundingClientRect();
        const x = ((cursorX - rect.left) / rect.width) * 100; const y = ((cursorY - rect.top) / rect.height) * 100;
        card.style.setProperty('--mouse-x', `${x}%`); card.style.setProperty('--mouse-y', `${y}%`);
        const edgeX = Math.max(0, Math.min(1, (cursorX - rect.left) / rect.width)); const edgeY = Math.max(0, Math.min(1, (cursorY - rect.top) / rect.height));
        const edgeTop = Math.max(0, 1 - edgeY); const edgeBottom = Math.max(0, edgeY); const edgeLeft = Math.max(0, 1 - edgeX); const edgeRight = Math.max(0, edgeX);
        const maxEdge = 0.45; const edgeScale = 0.12;
        card.style.setProperty('--edge-top', `${Math.min(maxEdge, edgeTop * edgeScale)}`); card.style.setProperty('--edge-bottom', `${Math.min(maxEdge, edgeBottom * edgeScale)}`);
        card.style.setProperty('--edge-left', `${Math.min(maxEdge, edgeLeft * edgeScale)}`); card.style.setProperty('--edge-right', `${Math.min(maxEdge, edgeRight * edgeScale)}`);
    });
}
function lerp(a, b, t) { return a + (b - a) * t; }
function animateTilt() {
    updateCardTargets();
    cards.forEach((card, i) => {
        current[i].rx = lerp(current[i].rx, target[i].rx, 0.09); current[i].ry = lerp(current[i].ry, target[i].ry, 0.09);
        current[i].scale = lerp(current[i].scale, target[i].scale, 0.1); current[i].glow = lerp(current[i].glow, target[i].glow, 0.1);
        card.style.transform = `rotateX(${current[i].rx}rad) rotateY(${current[i].ry}rad) scale(${current[i].scale})`;
        card.style.boxShadow = current[i].glow > 0.01 ? `0 0 ${18 + current[i].glow * 20}px rgba(120,120,140,${current[i].glow * 0.35})` : '0 8px 32px rgba(0,0,0,0.4)';
    });
    requestAnimationFrame(animateTilt);
}
requestAnimationFrame(animateTilt);
