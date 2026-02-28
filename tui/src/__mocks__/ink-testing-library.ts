/**
 * Minimal ink-testing-library mock for Jest.
 *
 * The real ink-testing-library depends on ink which ships as ESM-only and
 * cannot be loaded via ts-jest's CJS wrapper. This mock is not used by the
 * current app.test.tsx (which tests reducers directly), but is provided so
 * the import resolves without error if future tests import this module.
 */

type RenderResult = {
  lastFrame: () => string;
  stdin: { write: (input: string) => void };
  unmount: () => void;
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function render(element: unknown): RenderResult {
  return {
    lastFrame: () => "",
    stdin: { write: () => {} },
    unmount: () => {},
  };
}
