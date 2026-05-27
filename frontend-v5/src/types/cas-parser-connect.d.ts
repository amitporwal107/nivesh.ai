/**
 * Type stub for @cas-parser/connect widget SDK.
 * Replace with the real package types once the package is installed.
 */
declare module "@cas-parser/connect" {
  export interface CasConnectConfig {
    token: string;
    mode: string;
    onSuccess: (payload: unknown) => void;
    onError: (err: unknown) => void;
    onClose?: () => void;
  }

  export interface CasConnectInstance {
    open(): void;
    close(): void;
  }

  export type CasConnectFactory = (config: CasConnectConfig) => CasConnectInstance;

  const CasConnect: CasConnectFactory;
  export { CasConnect };
  export default CasConnect;
}
