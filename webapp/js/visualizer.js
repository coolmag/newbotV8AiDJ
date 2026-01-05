let canvas, ctx, audioCtx, analyser, dataArray;
let stars = [];
let isRunning = false;
let bassFilter = null;
let animationFrameId = null;
const STAR_COUNT = 100; // Много звезд
const BASE_SPEED = 0.5;
let smoothedVol = 0;

class Star {
    constructor() { this.reset(true); }
    reset(randomZ = false) {
        if (!canvas) return;
        this.x = (Math.random() - 0.5) * canvas.width * 2;
        this.y = (Math.random() - 0.5) * canvas.height * 2;
        this.z = randomZ ? Math.random() * canvas.width : canvas.width;
        this.size = Math.random() * 2; // Крупные звезды
        this.opacity = Math.random();
        this.color = Math.random() > 0.8 ? '#00f2ff' : '#ffffff'; // Иногда голубые
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
        const r = (1 - this.z / canvas.width) * (this.size + bassIntensity * 5);
        const alpha = (1 - this.z / canvas.width) * this.opacity;
        
        ctx.beginPath();
        ctx.fillStyle = this.color;
        ctx.globalAlpha = alpha;
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;
    }
}

async function initialize(audioElement) {
    if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
    if (isRunning) return;
    
    canvas = document.getElementById('visualizer-canvas');
    if (canvas) {
        ctx = canvas.getContext('2d');
        resize();
        window.addEventListener('resize', resize);
    }
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    stars = Array(STAR_COUNT).fill().map(() => new Star());
    
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!audioCtx) audioCtx = new AudioContext();
        if (!analyser) {
            const source = audioCtx.createMediaElementSource(audioElement);
            bassFilter = audioCtx.createBiquadFilter();
            bassFilter.type = 'lowshelf';
            bassFilter.frequency.value = 200;
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256; 
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
        bassFilter.gain.setTargetAtTime(active ? 8 : 0, now, 0.2);
    }
}

function resize() { if(canvas) { canvas.width = window.innerWidth; canvas.height = window.innerHeight; } }

function updateVUNeedles(volume) {
    // 0..1 -> -45..45 deg
    const angle = -45 + (volume * 90) + (Math.random() - 0.5) * 5;
    const clamped = Math.max(-50, Math.min(50, angle));
    const nL = document.getElementById('needle-l');
    const nR = document.getElementById('needle-r');
    if (nL) nL.style.transform = `rotate(${clamped}deg)`;
    if (nR) nR.style.transform = `rotate(${clamped * 0.95}deg)`;
}

function animate() {
    if (!isRunning || document.hidden) return;
    animationFrameId = requestAnimationFrame(animate);
    
    let bass = 0;
    let avgVol = 0;
    
    if (analyser) {
        analyser.getByteFrequencyData(dataArray);
        for(let i = 0; i < 6; i++) bass += dataArray[i];
        bass = bass / 6 / 255;
        
        let sum = 0;
        for(let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        avgVol = sum / dataArray.length / 128;
    }
    
    smoothedVol += (avgVol - smoothedVol) * 0.15;
    updateVUNeedles(smoothedVol);
    
    if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const currentSpeed = BASE_SPEED + (bass * 20); 
        stars.forEach(star => { 
            star.update(currentSpeed); 
            star.draw(ctx, cx, cy, bass); 
        });
    }
}

export const Visualizer = { initialize, setBassBoost };