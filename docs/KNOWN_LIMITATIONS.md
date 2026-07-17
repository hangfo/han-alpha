# Known limitations

1. Synthetic data is for engineering validation only. Any synthetic backtest metrics are meaningless as investment evidence.
2. The IBKR adapter cannot be integration-tested without the official local TWS API package and an authenticated paper session.
3. Polygon legacy snapshot field names vary by endpoint and plan; the parser supports explicit and legacy keys, but must be validated against the user's subscription response.
4. The current backtester is a one-position, long-only verifier rather than an institutional portfolio simulator.
5. Market impact uses a fixed slippage model and does not yet use order-book depth or participation rate.
6. Sector metadata is not yet supplied by a point-in-time symbol master.
7. SEC and FRED clients are present but not yet joined to a production evidence pipeline.
8. The API has no remote authentication and must bind to localhost.
9. Live orders are proposal-only in this version.
10. The simulated broker permits one active protected position per symbol; the risk engine blocks same-symbol pyramiding.
11. The FastAPI test stack currently emits one upstream deprecation warning regarding TestClient/httpx compatibility; runtime behavior passed.
