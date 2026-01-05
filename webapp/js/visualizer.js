let canvas, ctx, audioCtx, analyser, dataArray;
let stars = [];
let isRunning = false;
let bassFilter = null;
let animationFrameId = null;
const STAR_COUNT = 50; 
const BASE_SPEED = 0.3;

// Для VU метров
let smoothedVol = 0;

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
        const r = (1 - this.z / canvas.width) * (2 * this.size + bassIntensity * 2);
        const alpha = (1 - this.z / canvas.width);
        ctx.beginPath();
        ctx.fillStyle = `rgba(200, 200, 255, ${alpha})`;
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
    }
}

async function initialize(audioElement) {
    if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
    if (isRunning) return;
    
    // Canvas setup
    canvas = document.getElementById('visualizer-canvas');
    if (canvas) {
        ctx = canvas.getContext('2d', { alpha: false });
        resize();
        window.addEventListener('resize', resize);
    }
    
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
            analyser.fftSize = 256; 
            analyser.smoothingTimeConstant = 0.8; 
            
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
    // Volume 0 to 1. Map to angle -45deg to +45deg
    // Add some jitter for realism
    const jitter = (Math.random() - 0.5) * 2; 
    const angle = -45 + (volume * 90) + jitter;
    const clamped = Math.max(-50, Math.min(50, angle));
    
    const needleL = document.getElementById('needle-l');
    const needleR = document.getElementById('needle-r');
    
    if (needleL) needleL.style.transform = `rotate(${clamped}deg)`;
    // Right channel slightly different for stereo effect fake
    if (needleR) needleR.style.transform = `rotate(${clamped * 0.95}deg)`; 
}

function animate() {
    if (!isRunning || document.hidden) return;
    animationFrameId = requestAnimationFrame(animate);
    
    let bass = 0;
    let avgVol = 0;
    
    if (analyser) {
        analyser.getByteFrequencyData(dataArray);
        // Calculate bass (low frequencies)
        for(let i = 0; i < 10; i++) bass += dataArray[i];
        bass = bass / 10 / 255;
        
        // Calculate average volume for VU meter
        let sum = 0;
        for(let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        avgVol = sum / dataArray.length / 128; // Normalize roughly 0-1
    }
    
    // Smooth the volume for VU meter to avoid crazy shaking
    smoothedVol += (avgVol - smoothedVol) * 0.1;
    updateVUNeedles(smoothedVol);
    
    // Draw Space Background
    if (canvas && ctx) {
        ctx.fillStyle = '#101015'; // Darker space
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const currentSpeed = BASE_SPEED + (bass * 5); 
        
        stars.forEach(star => { 
            star.update(currentSpeed); 
            star.draw(ctx, cx, cy, bass); 
        });
    }
    
    // Update CSS variables for RGB glow
    if (bass > 0.01) {
        document.documentElement.style.setProperty('--beat', bass.toFixed(3));
    }
}

export const Visualizer = { initialize, setBassBoost };