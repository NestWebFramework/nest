<!-- nest:readme -->
# Publish and subscribe

Messages on named channels, heard by every process listening. The realtime broker relays its events over it, so a visitor on one worker of nest serve sees what was published on another.

**Version 0.1.1** · interface · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-pubsub` |
| name in a manifest | `pubsub` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/interfaces/pubsub |

## Using it

A module asks for it in its manifest (`requires: interfaces: [pubsub]`); the application binds a provider to it.
<!-- /nest:readme -->
