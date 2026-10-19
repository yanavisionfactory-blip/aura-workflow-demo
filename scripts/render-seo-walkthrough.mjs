// Emit the identical SVG screens used by the interactive static showcase.
// Rasterize with any SVG renderer, then encode as a captioned 66-second MP4.
import fs from "node:fs";
import path from "node:path";
import data from "../public/showcase/seo-audit/data.mjs";
import { renderFrame, initialState, tour } from "../public/showcase/seo-audit/view.mjs";
const directory = process.argv[2];
if (!directory) throw new Error("Supply a temporary frame output directory");
fs.mkdirSync(directory, { recursive: true });
const stamp = (seconds) => `${String(Math.floor(seconds / 3600)).padStart(2, "0")}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}.000`;
let captions = "WEBVTT\n\n";
for (let index = 0; index < tour.length; index++) {
  const scene = tour[index];
  fs.writeFileSync(path.join(directory, `scene-${String(index).padStart(2, "0")}.svg`), renderFrame(data, { ...initialState, ...scene.state }, { caption: scene.caption, chapter: `${index + 1} / ${tour.length}` }));
  captions += `${index + 1}\n${stamp(index * 6)} --> ${stamp((index + 1) * 6)}\n${scene.title}. ${scene.caption}\n\n`;
}
fs.writeFileSync(new URL("../public/showcase/seo-audit/walkthrough.vtt", import.meta.url), captions);
fs.writeFileSync(path.join(directory, "scenes.json"), JSON.stringify(tour));
console.log(JSON.stringify({ scenes: tour.length, seconds: tour.length * 6, directory }));
