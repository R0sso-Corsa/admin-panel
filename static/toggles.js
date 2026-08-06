(function() {
    if (!window.gsap || !window.Draggable) return;
    gsap.registerPlugin(Draggable);

    document.documentElement.dataset.bounce = 'true';
    document.documentElement.dataset.delta = 'true';
    document.documentElement.dataset.mapped = 'false';

    gsap.set('#goo feGaussianBlur', { attr: { stdDeviation: 2 } });
    gsap.set('#goo feColorMatrix', { attr: { values: `1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 16 -10` } });

    document.querySelectorAll('.liquid-toggle').forEach(toggle => {
        const service = toggle.dataset.service;
        const setting = toggle.dataset.setting;
        const initialRunning = toggle.dataset.running === 'true';
        
        // Initialize all toggles to OFF (0) unless explicitly set to ON via data-running
        const initialState = initialRunning ? 100 : 0;
        toggle.setAttribute('aria-pressed', String(initialRunning));
        toggle.style.setProperty('--complete', initialState);
        toggle.style.setProperty('--hue', 144);
        // Ensure data-active reflects actual state
        toggle.dataset.active = initialRunning ? 'true' : 'false';

        const sendToggleRequest = (newRunning) => {
            const row = toggle.closest('.service-row');
            const statusEl = row ? row.querySelector('.service-status') : null;
            if (service) {
                toggle.dataset.running = String(newRunning);
            }
            if (statusEl) {
                statusEl.textContent = newRunning ? 'running' : 'stopped';
                statusEl.className = `service-status ${newRunning ? 'running' : 'stopped'}`;
            }
            if (service) {
                fetch(`/api/services/${service}/toggle`, { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        const finalRunning = Boolean(data.running);
                        toggle.setAttribute('aria-pressed', String(finalRunning));
                        toggle.dataset.running = String(finalRunning);
                        toggle.style.setProperty('--complete', finalRunning ? 100 : 0);
                        if (statusEl) {
                            statusEl.textContent = finalRunning ? 'running' : 'stopped';
                            statusEl.className = `service-status ${finalRunning ? 'running' : 'stopped'}`;
                        }
                    })
                    .catch(() => {
                        toggle.setAttribute('aria-pressed', String(!newRunning));
                        toggle.dataset.running = String(!newRunning);
                        toggle.style.setProperty('--complete', !newRunning ? 100 : 0);
                        if (statusEl) {
                            statusEl.textContent = !newRunning ? 'running' : 'stopped';
                            statusEl.className = `service-status ${!newRunning ? 'running' : 'stopped'}`;
                        }
                    });
            }
        };

        const toggleState = async () => {
            toggle.dataset.pressed = true;
            toggle.dataset.active = true;
            const pressed = toggle.matches('[aria-pressed=true]');
            gsap.timeline({
                onComplete: () => {
                    gsap.delayedCall(0.05, () => {
                        toggle.dataset.active = false;
                        toggle.dataset.pressed = false;
                        const newPressed = !toggle.matches('[aria-pressed=true]');
                        toggle.setAttribute('aria-pressed', String(newPressed));
                        toggle.style.setProperty('--complete', newPressed ? 100 : 0);
                        sendToggleRequest(newPressed);
                    });
                },
            }).to(toggle, {
                '--complete': pressed ? 0 : 100,
                duration: 0.18,
                delay: 0
            });
        };

        const proxy = document.createElement('div');
        proxy.style.cssText = 'position:absolute; width:0; height:0; top:0; left:0; visibility:hidden;';
        document.body.appendChild(proxy);

        Draggable.create(proxy, {
            allowContextMenu: true,
            trigger: toggle,
            onDragStart: function () {
                this.hasDragged = true;
                const toggleBounds = toggle.getBoundingClientRect();
                const pressed = toggle.matches('[aria-pressed=true]');
                this.dragBounds = pressed ? toggleBounds.left - this.pointerX : toggleBounds.left + toggleBounds.width - this.pointerX;
                toggle.dataset.active = true;
            },
            onDrag: function () {
                const pressed = toggle.matches('[aria-pressed=true]');
                const dragged = this.x - this.startX;
                this.complete = gsap.utils.clamp(0, 100, pressed ? gsap.utils.mapRange(this.dragBounds, 0, 0, 100, dragged) : gsap.utils.mapRange(0, this.dragBounds, 0, 100, dragged));
                gsap.set(toggle, { '--complete': this.complete, '--delta': Math.min(Math.abs(this.deltaX), 12) });
            },
            onDragEnd: function () {
                const targetComplete = this.complete >= 50 ? 100 : 0;
                
                gsap.to(toggle, {
                    '--complete': targetComplete,
                    '--delta': 0,
                    duration: 0.35,
                    ease: 'power2.out',
                    onComplete: () => {
                        toggle.dataset.active = false;
                        toggle.dataset.pressed = false;
                        
                        const wasPressed = toggle.matches('[aria-pressed=true]');
                        const newPressed = targetComplete === 100;
                        
                        if (wasPressed !== newPressed) {
                            toggle.setAttribute('aria-pressed', String(newPressed));
                            sendToggleRequest(newPressed);
                        }
                    }
                });
            },
            onPress: function () {
                this.__pressTime = Date.now();
                this.hasDragged = false;
                this.complete = toggle.matches('[aria-pressed=true]') ? 100 : 0;
                toggle.dataset.active = 'true';
                toggle.dataset.pressed = 'true';
            },
            onRelease: function () {
                this.__releaseTime = Date.now();
                gsap.set(toggle, { '--delta': 0 });

                if (!this.hasDragged && (this.__releaseTime - this.__pressTime <= 250)) {
                    toggleState();
                    return;
                }

                if (!this.hasDragged) {
                    toggle.dataset.active = 'false';
                    toggle.dataset.pressed = 'false';
                    const currentPressed = toggle.matches('[aria-pressed=true]');
                    gsap.to(toggle, { 
                        '--complete': currentPressed ? 100 : 0, 
                        duration: 0.24 
                    });
                }
            }
        });

        toggle.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleState();
            }
        });
    });
})();