/** 화면 조각을 이미지(PNG)나 PDF 로 내려받는다.
 *
 * **PDF 라이브러리를 안 쓴다.** 필요한 것은 "그린 그림을 A4 에 나눠 붙이기"
 * 뿐이라, JPEG 을 그대로 품는 PDF 는 몇십 줄이면 만든다(PDF 가 JPEG 을
 * DCTDecode 로 바로 받아 준다). 한글 글꼴을 PDF 에 심을 필요도 없다 — 글자는
 * 이미 브라우저가 그림으로 그려 놓았다.
 *
 * **쪽을 나눌 때 말풍선 가운데를 자르지 않는다.** data-break 를 단 요소의
 * 아래 끝을 자를 수 있는 자리로 모아 두고, 한 쪽에 들어가는 가장 먼 자리에서
 * 자른다. 한 덩이가 한 쪽보다 길면 어쩔 수 없이 그 안에서 자른다.
 */

const A4_W = 595.28;
const A4_H = 841.89;
const MARGIN = 28;

export async function renderNode(node, scale = 2) {
  const html2canvas = (await import("html2canvas")).default;
  return html2canvas(node, { backgroundColor: "#ffffff", scale, useCORS: true });
}

/** node 안의 [data-break] 요소 아래 끝(캔버스 픽셀 기준). */
export function breakPoints(node, scale = 2) {
  const top = node.getBoundingClientRect().top;
  return [...node.querySelectorAll("[data-break]")]
    .map((el) => Math.round((el.getBoundingClientRect().bottom - top) * scale))
    .sort((a, b) => a - b);
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function downloadPng(canvas, filename) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => { downloadBlob(blob, filename); resolve(); }, "image/png");
  });
}

function jpegBytes(canvas) {
  const b64 = canvas.toDataURL("image/jpeg", 0.92).split(",")[1];
  const bin = window.atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

/** 긴 그림을 A4 높이에 맞춰 여러 장으로 자른다. */
export function sliceCanvas(canvas, breaks = []) {
  const usableW = A4_W - MARGIN * 2;
  const usableH = A4_H - MARGIN * 2;
  const pageH = Math.floor(canvas.width * (usableH / usableW));   // 한 쪽에 들어가는 픽셀 높이
  const slices = [];
  // 마지막 내용의 아래 끝. 그 밑은 여백뿐이라, 여백 때문에 빈 쪽이 하나 더
  // 생기지 않도록 여기까지만 쪽을 센다.
  const contentEnd = breaks.length ? Math.min(breaks[breaks.length - 1], canvas.height) : canvas.height;
  let y = 0;
  while (y < contentEnd - 1) {
    let end = Math.min(y + pageH, canvas.height);
    if (contentEnd <= y + pageH) {
      // 남은 내용이 이 쪽에 다 들어간다. 여백은 들어가는 만큼만 붙인다.
    } else if (end < canvas.height) {
      // 한 쪽의 1/3 이상은 채우는 자리에서만 자른다 — 너무 일찍 자르면 빈 쪽이 많아진다.
      const cut = breaks.filter((b) => b > y + pageH / 3 && b <= end).pop();
      if (cut) end = cut;
    }
    const part = document.createElement("canvas");
    part.width = canvas.width;
    part.height = end - y;
    const ctx = part.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, part.width, part.height);
    ctx.drawImage(canvas, 0, y, canvas.width, end - y, 0, 0, canvas.width, end - y);
    slices.push(part);
    y = end;
  }
  return slices;
}

/** 캔버스 여러 장 → A4 PDF(Blob). 한 장이 한 쪽이다. */
export function canvasesToPdf(canvases) {
  const enc = new window.TextEncoder();
  const chunks = [];
  const offsets = [];
  let size = 0;
  const push = (part) => {
    const bytes = typeof part === "string" ? enc.encode(part) : part;
    chunks.push(bytes);
    size += bytes.length;
  };
  const obj = (n, body) => {
    offsets[n] = size;
    push(`${n} 0 obj\n`);
    body();
    push("\nendobj\n");
  };

  // 1: 카탈로그, 2: 쪽 목록, 그 뒤로 쪽마다 [쪽, 내용, 그림] 세 개씩.
  const n = canvases.length;
  const pageIds = canvases.map((_, i) => 3 + i * 3);
  push("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");
  obj(1, () => push("<< /Type /Catalog /Pages 2 0 R >>"));
  obj(2, () => push(`<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${n} >>`));

  canvases.forEach((cv, i) => {
    const pageId = pageIds[i];
    const contentId = pageId + 1;
    const imageId = pageId + 2;
    const w = A4_W - MARGIN * 2;
    const h = w * (cv.height / cv.width);
    const draw = `q ${w.toFixed(2)} 0 0 ${h.toFixed(2)} ${MARGIN} ${(A4_H - MARGIN - h).toFixed(2)} cm /Im0 Do Q`;
    obj(pageId, () => push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${A4_W} ${A4_H}] ` +
      `/Resources << /XObject << /Im0 ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`));
    obj(contentId, () => {
      push(`<< /Length ${enc.encode(draw).length} >>\nstream\n`);
      push(draw);
      push("\nendstream");
    });
    const jpg = jpegBytes(cv);
    obj(imageId, () => {
      push(`<< /Type /XObject /Subtype /Image /Width ${cv.width} /Height ${cv.height} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpg.length} >>\nstream\n`);
      push(jpg);
      push("\nendstream");
    });
  });

  const total = 3 + n * 3;
  const xref = size;
  let table = `xref\n0 ${total}\n0000000000 65535 f \n`;
  for (let i = 1; i < total; i += 1) table += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  push(table);
  push(`trailer\n<< /Size ${total} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  return new Blob(chunks, { type: "application/pdf" });
}
