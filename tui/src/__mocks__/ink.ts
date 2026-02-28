/**
 * Minimal Ink mock for Jest.
 *
 * Ink and its dependency tree (ansi-escapes, yoga-layout, etc.) are ESM-only
 * packages that cannot be loaded through ts-jest's CommonJS wrapper. This mock
 * replaces `ink` with lightweight React pass-throughs so hook and state tests
 * can run without a real terminal environment.
 */
import * as React from "react";

// Box and Text render their children as plain React fragments.
export const Box = ({
  children,
}: {
  children?: React.ReactNode;
  [key: string]: unknown;
}) => React.createElement(React.Fragment, null, children);

export const Text = ({
  children,
}: {
  children?: React.ReactNode;
  [key: string]: unknown;
}) => React.createElement(React.Fragment, null, children);

// useInput is a no-op in tests; real keyboard capture requires a terminal.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const useInput = (handler: unknown): void => {};

// render returns a minimal handle.
export const render = (
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  element: unknown,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  options?: unknown,
): { unmount: () => void; waitUntilExit: () => Promise<void> } => ({
  unmount: () => {},
  waitUntilExit: () => Promise.resolve(),
});
