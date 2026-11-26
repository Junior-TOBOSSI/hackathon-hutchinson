"""ARGOS integration contracts shared by the five workstreams.

- ``edge_events``     : versioned Edge -> Core event envelope, batch and acknowledgement.
- ``core_api``        : read models served by ARGOS Core to the Supervisor / AI Leader UIs.
- ``mlops``           : dataset, training, evaluation, model package, deployment, monitoring.
- ``vision``          : PPE / Behavior detector interfaces and proposed contract extensions.
- ``safety_composite``: a safety Analyzer composing a PPE and a Behavior detector.

None of these modules changes the historical contracts (``visionhub/contracts.py``).
"""
