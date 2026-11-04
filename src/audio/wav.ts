export function encodeWav(buffer: AudioBuffer): Blob {
  const channels = buffer.numberOfChannels,
    samples = buffer.length;
  const bytes = new ArrayBuffer(44 + samples * channels * 2),
    view = new DataView(bytes);
  const string = (offset: number, value: string): void => {
    for (let i = 0; i < value.length; i++)
      view.setUint8(offset + i, value.charCodeAt(i));
  };
  string(0, "RIFF");
  view.setUint32(4, bytes.byteLength - 8, true);
  string(8, "WAVE");
  string(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  string(36, "data");
  view.setUint32(40, samples * channels * 2, true);
  const data = Array.from({ length: channels }, (_, i) =>
    buffer.getChannelData(i)
  );
  for (let i = 0; i < samples; i++)
    for (let ch = 0; ch < channels; ch++) {
      const value = Math.max(-1, Math.min(1, data[ch][i]));
      view.setInt16(
        44 + (i * channels + ch) * 2,
        value * (value < 0 ? 32768 : 32767),
        true
      );
    }
  return new Blob([bytes], { type: "audio/wav" });
}
export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
