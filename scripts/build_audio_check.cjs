const fs = require("node:fs");
const path = require("node:path");
const { parseArgs } = require("node:util");

const { values } = parseArgs({
  options: {
    typescript: { type: "string" },
    out: { type: "string" },
    zod: { type: "string" },
  },
});
const ts = require(values.typescript || "typescript");
const output = values.out || ".verification/audio";
const zod = values.zod || path.dirname(require.resolve("zod/package.json"));
const vendor = path.join(output, "vendor/zod");
fs.mkdirSync(vendor, { recursive: true });
if (path.resolve(zod) !== path.resolve(vendor))
  fs.cpSync(zod, vendor, { recursive: true });
const sources = [
  "src/domain/timing.ts",
  "src/domain/arrangement.ts",
  "src/domain/project.ts",
  "src/domain/music.ts",
  "src/domain/motion.ts",
  "src/domain/pitch.ts",
  "src/audio/engine.ts",
  "src/audio/demo.ts",
  "src/audio/wav.ts",
];
for (const file of sources) {
  const result = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    fileName: file,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
      strict: true,
    },
    reportDiagnostics: true,
  });
  if (result.diagnostics?.length) throw new Error(`Cannot transpile ${file}`);
  const target = path.join(output, file.replace(/\.ts$/, ".js"));
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(
    target,
    result.outputText.replace(/from "(\.[^"]+)"/g, 'from "$1.js"')
  );
}
fs.copyFileSync("tests/audio/harness.html", path.join(output, "index.html"));
process.stdout.write(
  `Built isolated audio check in ${output}. This is not the studio UI.\n`
);
