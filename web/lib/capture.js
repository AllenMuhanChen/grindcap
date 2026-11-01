// Screen capture of the MapleStory window with getDisplayMedia, plus the numbers needed to judge it:
// how often frames actually arrive, at what size, and what happens while this tab is in the background.
import { fromImageData } from './img.js';

export class Capture {
  constructor(onEnd = () => {}) {
    this.onEnd = onEnd;
    this.stats = { method: null, grabs: 0, fails: 0, hiddenGrabs: 0, maxGap: 0, last: 0, size: null, log: [] };
  }

  async start() {
    this.stream = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'window', frameRate: { ideal: 5, max: 10 } },
      audio: false,
      selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude', monitorTypeSurfaces: 'exclude',
    });
    this.track = this.stream.getVideoTracks()[0];
    this.track.addEventListener('ended', () => { this.note('sharing stopped'); this.onEnd(); });
    const s = this.track.getSettings();
    this.note(`sharing ${s.displaySurface || '?'} ${s.width}x${s.height} @ ${s.frameRate || '?'} fps`);
    this.imageCapture = 'ImageCapture' in window ? new ImageCapture(this.track) : null;
    this.video = document.createElement('video');
    this.video.muted = true; this.video.playsInline = true;
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    this.stats.method = this.imageCapture ? 'ImageCapture.grabFrame' : 'video element';
    return s;
  }

  get live() { return this.track && this.track.readyState === 'live'; }

  stop() { if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); }

  note(text) {
    const line = `${new Date().toLocaleTimeString()}  ${text}`;
    this.stats.log.unshift(line);
    this.stats.log.length = Math.min(this.stats.log.length, 200);
  }

  /** The current frame as an RGB mat (or the raw ImageData with asMat = false), or null. */
  async grab(asMat = true) {
    if (!this.live) return null;
    let bmp = null;
    try {
      if (this.imageCapture) {
        bmp = await Promise.race([this.imageCapture.grabFrame(),
          new Promise((_, rej) => setTimeout(() => rej(new Error('grabFrame timed out (3 s)')), 3000))]);
      }
    } catch (e) {
      this.stats.fails++;
      if (this.stats.fails <= 5 || this.stats.fails % 50 === 0) this.note(`grabFrame failed (${e.message}); using the video element`);
    }
    let src = bmp, w, h;
    if (bmp) { w = bmp.width; h = bmp.height; }
    else if (this.video && this.video.videoWidth) { src = this.video; w = this.video.videoWidth; h = this.video.videoHeight; }
    else return null;
    const cv = new OffscreenCanvas(w, h);
    const g = cv.getContext('2d', { willReadFrequently: true });
    g.drawImage(src, 0, 0);
    if (bmp) bmp.close();
    const id = g.getImageData(0, 0, w, h);
    const now = performance.now();
    if (this.stats.last) this.stats.maxGap = Math.max(this.stats.maxGap, (now - this.stats.last) / 1000);
    this.stats.last = now;
    this.stats.grabs++;
    if (document.hidden) this.stats.hiddenGrabs++;
    const size = `${w}x${h}`;
    if (size !== this.stats.size) { if (this.stats.size) this.note(`frame size changed to ${size}`); this.stats.size = size; }
    this.lastImageData = id;
    return asMat ? fromImageData(id) : id;
  }

  /** Download the last frame as a PNG (to compare with what the Python app captures). */
  async saveLastFrame() {
    if (!this.lastImageData) return;
    const id = this.lastImageData, cv = new OffscreenCanvas(id.width, id.height);
    cv.getContext('2d').putImageData(id, 0, 0);
    const blob = await cv.convertToBlob({ type: 'image/png' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `grindcap-browser-frame-${Date.now()}.png`;
    a.click();
  }
}

/** A timer run from a dedicated worker. Chrome throttles a hidden page's own timers (to about once a
 * second, or once a minute after 5 minutes); a worker's timers are expected to keep their pace. The
 * capture panel shows whether that holds (frames grabbed while hidden, longest gap). */
export function ticker(ms, fn) {
  const src = `let id=null;onmessage=(e)=>{clearInterval(id);if(e.data>0)id=setInterval(()=>postMessage(Date.now()),e.data);}`;
  const w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
  w.onmessage = () => fn();
  w.postMessage(ms);
  return { stop: () => w.postMessage(0) };
}
