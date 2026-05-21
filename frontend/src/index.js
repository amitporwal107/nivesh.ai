// Build-time dispatcher between the V2 and V3 bundles.
//
// `process.env.REACT_APP_BUNDLE_TARGET` is replaced by webpack's DefinePlugin
// at build time, so the `if` below becomes a constant after compilation.
// Terser then dead-code-eliminates the unused branch, meaning:
//   - the V2 bundle ships zero V3 code
//   - the V3 bundle ships zero V2 code
//
// Default ("v2") preserves backward compatibility for tooling that runs
// `yarn build` without specifying a target.

if (process.env.REACT_APP_BUNDLE_TARGET === "v3") {
  require("./index.v3");
} else {
  require("./index.v2");
}
