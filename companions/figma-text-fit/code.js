/* Measure the height at the original width and remove the probe after every run. */
const typeFields = ["fontName", "fontSize", "lineHeight", "letterSpacing", "textCase"];
const selectedText = () => {
  const selection = figma.currentPage.selection;
  return selection.length === 1 && selection[0].type === "TEXT" ? selection[0] : null;
};

function selectionMessage() {
  const node = selectedText();
  const info = node ? { id: node.id, name: node.name, width: node.width, height: node.height } : null;
  figma.ui.postMessage({ type: "selection", info });
}

function parseCopies(input) {
  if (typeof input !== "string" || input.length > 16000) throw Error("Split long input into smaller batches.");
  const lines = input.split(/\r?\n/).filter(line => line.trim());
  if (!lines.length || lines.length > 12) throw Error("Enter between 1 and 12 localized lines.");
  const seen = new Set();
  return lines.map((line, index) => {
    const separator = line.search(/[|｜\t]/);
    const locale = line.slice(0, separator).trim();
    const copy = line.slice(separator + 1).trim().replace(/\\n/g, "\n");
    if (separator < 1 || !locale || !copy || locale.length > 24 || copy.length > 1200) {
      throw Error("Line " + (index + 1) + ": use Locale | Copy, up to 1200 characters per line.");
    }
    const key = locale.toLowerCase();
    if (seen.has(key)) throw Error("Duplicate locale: " + locale + ". Use distinct variant names, such as DE-A and DE-B.");
    seen.add(key);
    return { locale, copy };
  });
}

async function measure(node, copies) {
  if (!node.characters.length || node.hasMissingFont) throw Error("Select a nonempty text layer with available fonts.");
  if (typeFields.some(field => node[field] === figma.mixed)) throw Error("Choose a text layer with uniform typography.");
  if (node.getStyledTextSegments(["listOptions"]).some(seg => seg.listOptions.type !== "NONE")) {
    throw Error("Choose a plain text layer. List formatting is unsupported.");
  }
  try { await figma.loadFontAsync(node.fontName); }
  catch (_) { throw Error("Install or enable the source font and try again."); }
  if (node.removed || selectedText() !== node) throw Error("The selection changed. Run the check again.");
  const width = node.width;
  const height = node.height;
  let probe;
  try {
    probe = figma.createText();
    probe.name = "Promo Proof — measurement";
    probe.opacity = 0;
    probe.fontName = node.fontName;
    probe.fontSize = node.fontSize;
    probe.lineHeight = node.lineHeight;
    probe.letterSpacing = node.letterSpacing;
    probe.textCase = node.textCase;
    probe.paragraphSpacing = node.paragraphSpacing;
    probe.paragraphIndent = node.paragraphIndent;
    probe.textAlignHorizontal = node.textAlignHorizontal;
    probe.leadingTrim = node.leadingTrim;
    probe.hangingPunctuation = node.hangingPunctuation;
    probe.textAutoResize = "NONE";
    probe.resize(Math.max(0.01, width), Math.max(0.01, height));
    probe.textAutoResize = "HEIGHT";
    return copies.map(({locale, copy}) => {
      probe.characters = copy;
      const required = probe.height;
      const difference = required - height;
      return { locale, copy, required, extra: difference > 0.01 ? Math.ceil(difference) : 0 };
    });
  } finally {
    if (probe && !probe.removed) probe.remove();
  }
}

figma.showUI(__html__, { width: 420, height: 530, themeColors: true });
figma.on("selectionchange", selectionMessage);
let running = false;
figma.ui.onmessage = async message => {
  if (!message) return;
  if (message.type === "ready") { selectionMessage(); return; }
  if (message.type !== "check" || running) return;
  running = true;
  const revision = message.revision;
  try {
    const node = selectedText();
    if (!node || node.id !== message.id) throw Error("Select one text layer and run the check.");
    const copies = parseCopies(message.input);
    const results = await measure(node, copies);
    figma.ui.postMessage({ type: "result", id: node.id, revision, results, height: node.height, width: node.width });
  } catch (error) {
    figma.ui.postMessage({ type: "error", revision, text: error.message || "Check the selected layer and its fonts." });
  } finally { running = false; }
};
