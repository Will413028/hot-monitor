import { cpSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = path.join(root, ".next");
cpSync(path.join(root, "public"), path.join(output, "standalone", "public"), { recursive: true });
cpSync(path.join(output, "static"), path.join(output, "standalone", ".next", "static"), { recursive: true });
