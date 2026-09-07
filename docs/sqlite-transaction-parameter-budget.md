# SQLite transaction parameter budget

`SQLiteTransactionTarget(max_params=N)` bounds the number of bind parameters accepted by each transaction statement and by the final observation statement before SQLite execution. The default is 999 and the value must be a positive integer.

The bound is carried in the worker argv, so changing it changes replay identity. Exactly `N` scalar parameters are accepted; the next parameter is rejected deterministically as a protocol error with exit code 2. Transaction and observation statements use the same ceiling.

This limit complements the request/statement count, SQL byte, JSON depth, VM-step, result row/column/value/aggregate byte, transcript-result byte, process timeout, stdin, and process output budgets. It specifically prevents many individually small scalar binds from turning one statement into unbounded bind orchestration work.

Real-process integration coverage exercises both transaction and observation enforcement and verifies that asymmetric candidate/oracle budgets are classified as `product_mismatch`, not infrastructure failure.
