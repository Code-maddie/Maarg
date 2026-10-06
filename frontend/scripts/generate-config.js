#!/usr/bin/env node
/**
 * Generates sidecar-site/js/config.js from the environment.
 *
 * The site is plain HTML with no bundler, so it cannot read environment
 * variables at runtime. This writes the one file that carries per-deployment
 * values, and runs both locally (`npm run dev`) and on Vercel (build command).
 *
 * The generated file is git-ignored, which is the point: the Google Maps key
 * lives in the deployment environment, not in the repository.
 *
 * Environment:
 *   MAARG_API_BASE_URL          Backend origin, e.g. https://sh205-api.onrender.com
 *   MAARG_GOOGLE_MAPS_API_KEY   Maps JavaScript API + Directions API key
 */

const fs = require("node:fs");
const path = require("node:path");

const OUTPUT = path.join(__dirname, "..", "sidecar-site", "js", "config.js");

// Local defaults so a fresh checkout runs with no setup. Production values
// always come from the environment.
const apiBaseUrl = (process.env.MAARG_API_BASE_URL || "http://localhost:8000")
  .trim()
  .replace(/\/+$/, "");
const mapsKey = (process.env.MAARG_GOOGLE_MAPS_API_KEY || "").trim();

const contents = `/* GENERATED FILE - DO NOT EDIT, DO NOT COMMIT.
   Written by frontend/scripts/generate-config.js from the environment.
   Change the values via MAARG_API_BASE_URL / MAARG_GOOGLE_MAPS_API_KEY.

   Without a Maps key every map falls back to Leaflet automatically, so the
   site stays fully usable. Restrict the key in the Google Cloud Console:
   HTTP referrers = your deployed domain(s), APIs = Maps JavaScript API and
   Directions API. */
window.MAARG_CONFIG = {
  API_BASE_URL: ${JSON.stringify(apiBaseUrl)},
  GOOGLE_MAPS_API_KEY: ${JSON.stringify(mapsKey)},
};
`;

fs.writeFileSync(OUTPUT, contents, "utf8");

console.log(`Wrote ${path.relative(process.cwd(), OUTPUT)}`);
console.log(`  API_BASE_URL        ${apiBaseUrl}`);
console.log(
  `  GOOGLE_MAPS_API_KEY ${mapsKey ? "set" : "not set - maps fall back to Leaflet"}`
);
