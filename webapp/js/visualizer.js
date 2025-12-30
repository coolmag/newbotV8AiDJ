let canvas, ctx, audioCtx, analyser, dataArray;
let stars = [];
let isRunning = false;
let bassFilter = null;
let animationFrameId = null;
const STAR_COUNT = 60; 
const BASE_SPEED = 0.5;

class Star {
    constructor() { this.reset(true); }
    reset(randomZ = false) {
        if (!canvas) return;
        this.x = (Math.random() - 0.5) * canvas.width * 2;
        this.y = (Math.random() - 0.5) * canvas.height * 2;
        this.z = randomZ ? Math.random() * canvas.width : canvas.width;
        this.size = Math.random();
    }
    update(speed) {
        if (!canvas) return;
        this.z -= speed;
        if (this.z < 1) this.reset();
    }
    draw(ctx, centerX, centerY, bassIntensity) {
        if (!canvas) return;
        const x = (this.x / this.z) * centerX + centerX;
        const y = (this.y / this.z) * centerY + centerY;
        const r = (1 - this.z / canvas.width) * (3 * this.size + bassIntensity * 2);
        const alpha = (1 - this.z / canvas.width);
        ctx.beginPath();
        ctx.fillStyle = `rgba(180, 220, 255, ${alpha})`;
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
    }
}

async function initialize(audioElement) {
    if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
    if (isRunning) return;
    canvas = document.getElementById('visualizer-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d', { alpha: false }); 
    resize();
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    stars = Array(STAR_COUNT).fill().map(() => new Star());
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!audioCtx) audioCtx = new AudioContext();
        if (audioCtx.state === 'suspended') await audioCtx.resume();
        if (!analyser) {
            const source = audioCtx.createMediaElementSource(audioElement);
            bassFilter = audioCtx.createBiquadFilter();
            bassFilter.type = 'lowshelf';
            bassFilter.frequency.value = 200;
            bassFilter.gain.value = 0;
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 128;
            analyser.smoothingTimeConstant = 0.85;
            source.connect(bassFilter);
            bassFilter.connect(analyser);
            analyser.connect(audioCtx.destination);
        }
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        isRunning = true;
        animate();
    } catch (e) { console.warn("Visualizer init warning:", e); }
}

function handleVisibilityChange() {
    if (document.hidden) { isRunning = false; if (animationFrameId) cancelAnimationFrame(animationFrameId); } 
    else { if (!isRunning) { isRunning = true; resize(); animate(); } }
}

function setBassBoost(active) {
    if (bassFilter && audioCtx) {
        const now = audioCtx.currentTime;
        const value = active ? 10 : 0;
        bassFilter.gain.setTargetAtTime(value, now, 0.2);
    }
}

function resize() { if(canvas) { canvas.width = window.innerWidth; canvas.height = window.innerHeight; } }

function animate() {
    if (!isRunning || document.hidden) return;
    animationFrameId = requestAnimationFrame(animate);
    let bass = 0;
    if (analyser) {
        analyser.getByteFrequencyData(dataArray);
        for(let i = 0; i < 8; i++) bass += dataArray[i];
        bass = bass / 8 / 255;
    }
    if (canvas && ctx) {
        ctx.fillStyle = '#050510'; 
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const currentSpeed = BASE_SPEED + (bass * 8); 
        stars.forEach(star => { star.update(currentSpeed); star.draw(ctx, cx, cy, bass); });
    }
    if (bass > 0.05) document.documentElement.style.setProperty('--beat', bass.toFixed(3));
}

export const Visualizer = { initialize, setBassBoost };