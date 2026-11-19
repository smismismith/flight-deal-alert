import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// base 를 상대 경로로 두어 GitHub Pages 프로젝트 하위 경로에서도 같은 빌드를 사용한다.
export default defineConfig({
  base: "./",
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
