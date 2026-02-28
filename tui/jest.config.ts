import type { Config } from "jest";

const config: Config = {
  preset: "ts-jest/presets/default-esm",
  testEnvironment: "node",
  extensionsToTreatAsEsm: [".ts", ".tsx"],
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json"],
  transform: {
    "^.+\\.(ts|tsx)$": [
      "ts-jest",
      {
        useESM: true,
        tsconfig: "<rootDir>/tsconfig.json"
      }
    ]
  },
  moduleNameMapper: {
    "^(\\.{1,2}/.*)\\.js$": "$1",
    // Ink and its ESM-only dependency tree cannot be loaded via ts-jest's CJS
    // wrapper. Mock the entire ink surface used by components so tests that
    // exercise hooks and reducers in isolation can run without a real terminal.
    "^ink$": "<rootDir>/src/__mocks__/ink.ts",
    "^ink-testing-library$": "<rootDir>/src/__mocks__/ink-testing-library.ts"
  },
  passWithNoTests: true,
  // Prevent Jest from double-running compiled output in dist/
  testPathIgnorePatterns: ["/node_modules/", "/dist/"]
};

export default config;
