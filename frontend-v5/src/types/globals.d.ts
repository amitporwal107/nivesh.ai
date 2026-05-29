export {};

declare global {
  interface Window {
    __FLAGS__: {
      isEnabled(key: string): boolean;
      disableFlag(key: string, reason?: string): void;
      enableFlag(key: string): void;
      getAll(): Record<string, boolean>;
    };
    __APP_HEALTH__: {
      get(): ReadonlyMap<string, unknown>;
      getOverall(): string;
    };
    __DIAGNOSTICS__: {
      build(): unknown;
    };
  }
}
