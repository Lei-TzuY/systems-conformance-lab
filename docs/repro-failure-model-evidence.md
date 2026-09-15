# Repro failure-model evidence

`repro_evidence.load_evidenced_repro_bundle` layers a typed fault/recovery evidence contract on top of the canonical repro loader. The canonical loader still owns bundle layout, input digest, execution/comparison consistency, failure-signature consistency, and replay-context validation.

Legacy repro metadata with none of the evidence fields remains accepted. Once any of `failure_model`, `remount_performed`, or `power_loss_recovery_proven` is present, all three are required and type checked. This prevents archive or replay consumers from retaining only the attractive part of a durability claim while dropping its qualifying boundary.

The known `process-kill-same-mount` model is intentionally strict: `remount_performed` and `power_loss_recovery_proven` must both be false. A process-kill experiment on the same mounted filesystem is therefore never upgraded into reboot, remount, or power-loss evidence by repro transport.

The integration test writes a real differential repro bundle through `DifferentialHarness`, reloads it through the evidenced loader, and verifies the metadata survives exactly. A tampered manifest that upgrades the power-loss claim is rejected before any target process is launched.
