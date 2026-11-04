const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const { parseArgs } = require("node:util");
const { values } = parseArgs({
  options: {
    typescript: { type: "string" },
    zod: { type: "string" },
    check: { type: "boolean" },
  },
});
const ts = require(values.typescript
  ? path.resolve(values.typescript)
  : "typescript");
const zod = path.resolve(
  values.zod || path.dirname(require.resolve("zod/package.json"))
);
const files = [];
function scan(directory) {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) scan(file);
    else if (file.endsWith(".ts") && !file.endsWith(".test.ts"))
      files.push(file);
  }
}
for (const directory of ["audio", "browser", "domain", "services", "storage"])
  scan(path.join("src", directory));
const options = {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  lib: ["lib.es2022.d.ts", "lib.dom.d.ts", "lib.dom.iterable.d.ts"],
  types: [],
  strict: true,
  noUnusedLocals: true,
  noUnusedParameters: true,
  skipLibCheck: true,
  noEmitOnError: true,
  rootDir: path.resolve("src"),
  outDir: path.resolve("dist/modules"),
  baseUrl: process.cwd(),
  paths: { zod: [path.join(zod, "index.d.ts")] },
};
const program = ts.createProgram(files, options);
const diagnostics = ts.getPreEmitDiagnostics(program);
if (diagnostics.length) {
  process.stderr.write(
    ts.formatDiagnosticsWithColorAndContext(diagnostics, {
      getCurrentDirectory: () => process.cwd(),
      getCanonicalFileName: (name) => name,
      getNewLine: () => "\n",
    })
  );
  process.exit(1);
}
if (values.check) {
  process.stdout.write(`TypeScript: ${files.length} modules checked.\n`);
  process.exit(0);
}
program.emit();
function extensions(directory) {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) extensions(file);
    else if (file.endsWith(".js")) {
      const relative = path
        .relative(path.dirname(file), "dist/vendor/zod/index.js")
        .split(path.sep)
        .join("/");
      fs.writeFileSync(
        file,
        fs
          .readFileSync(file, "utf8")
          .replace(/from "(\.[^"]+)"/g, 'from "$1.js"')
          .replace(
            /from "zod"/g,
            `from "${relative.startsWith(".") ? relative : "./" + relative}"`
          )
      );
    }
  }
}
extensions("dist/modules");
fs.mkdirSync("dist/vendor/zod", { recursive: true });
fs.cpSync(zod, "dist/vendor/zod", { recursive: true });
for (const file of ["index.html", "shell.css"])
  fs.copyFileSync(path.join("web", file), path.join("dist", file));
fs.cpSync("public", "dist", { recursive: true });
fs.mkdirSync("dist/assets", { recursive: true });
fs.copyFileSync(
  "godot/assets/NotoSans-Regular.ttf",
  "dist/assets/NotoSans-Regular.ttf"
);
fs.copyFileSync("godot/assets/OFL.txt", "dist/assets/OFL.txt");
fs.writeFileSync(
  "dist/config.js",
  `window.JUNK_CONFIG = ${JSON.stringify({
    apiBase: process.env.JUNK_API_BASE || "/api",
  })};\n`
);
const timingContext = { exports: {} };
vm.runInNewContext(
  ts.transpileModule(fs.readFileSync("src/domain/timing.ts", "utf8"), {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText,
  timingContext
);
const timing = timingContext.exports;
fs.writeFileSync(
  "godot/scripts/loop_timing.gd",
  `# Generated from src/domain/timing.ts by build_browser.cjs.\nclass_name JunkLoopTiming\nextends RefCounted\n\nconst BARS: int = ${timing.loopBars}\nconst BEATS: float = ${timing.loopBeats}.0\nconst STEPS: int = ${timing.loopSteps}\n`
);
const context = {
  exports: {},
  require: (name) => {
    if (name === "zod") return require(path.join(zod, "index.cjs"));
    if (name === "./timing") return timing;
    throw new Error(`Unexpected demo dependency ${name}`);
  },
  crypto: webcrypto,
};
const demo = ts.transpileModule(
  fs.readFileSync("src/domain/project.ts", "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }
);
vm.runInNewContext(demo.outputText, context);
fs.writeFileSync(
  "godot/assets/demo.json",
  JSON.stringify(context.exports.demoProject(), null, 2)
);
process.stdout.write(
  `Browser TypeScript checked and emitted (${files.length} modules). Runtime dependency: Zod.\n`
);
