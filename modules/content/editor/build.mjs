// Builds the editor into the content module's static folder: one file, no imports, minified.
//   cd modules/content/editor && npm ci && npm run build
import { build } from "esbuild";

await build({
  entryPoints: ["src/editor.js"],
  bundle: true,
  minify: true,
  format: "iife",
  target: ["es2020"],
  legalComments: "eof",
  outfile: "../src/nest_content/static/editor/editor.js",
  banner: { js: "/* nest content editor: Tiptap and ProseMirror (MIT), see editor/package.json */" },
});
console.log("✓ ../src/nest_content/static/editor/editor.js");
