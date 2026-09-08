# Post-exit descendant cleanup

`run_process` treats target code as untrusted. A root target may spawn descendants and then exit before they do. Waiting indefinitely for descendants that retain stdin, stdout, or stderr would let a target escape the runner timeout after its root process has already terminated. A descendant can also redirect all inherited stdio and remain alive after the root exits, which must not silently turn a process-isolated test into a background workload.

After the root exits, the runner therefore keeps post-exit cleanup bounded. On POSIX each target starts in its own session. The runner probes that dedicated process group after reaping the root; if any member remains, the run is classified as an infrastructure failure with `ProcessTreeLeak` and the group is killed even when every stdio worker has already drained. The existing bounded stdio-drain path remains as a second guard and applies on every supported platform; on Windows it invokes the existing `taskkill /T /F` cleanup when inherited pipes reveal a surviving tree. The runner never uses shell interpolation.

This classification is intentionally distinct from a product mismatch: a descendant outliving the target root is an execution-environment failure, not target output that an oracle should compare.

Focused regressions launch real Python targets for both cases. One descendant inherits the harness pipes and proves post-exit draining remains bounded. A second POSIX descendant redirects stdin/stdout/stderr to `DEVNULL`, sleeps, and attempts a delayed marker write; the runner must detect the surviving process group, kill it, report `ProcessTreeLeak`, and prevent the marker from being created.

The POSIX group check covers descendants that remain in the dedicated target session/process group. A descendant that deliberately creates a new session escapes that operating-system boundary; preventing that requires a stronger containment primitive such as a container/cgroup or platform job object and is outside this runner contract.
