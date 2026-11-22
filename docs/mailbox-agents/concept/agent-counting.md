# Concept: the agent `counting`

Part of the [concept](../CONCEPT.md).

Counts every message created or sent, asks no model and declares no
action. Each ends `done` with the label `counted`. It checks a deployment
end to end, feed, state file, steps, report and health, before any agent
may change a message, and the tests of the commands and of the health
check run on it.
