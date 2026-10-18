export default function requestAnimationFrame(callback: FrameRequestCallback): number {
  return setTimeout(() => {
    callback(Date.now());
  }, 1000 / 60) as unknown as number;
}