# Companion knowledge and delivery

Separate what the companion knows from what the player has heard. Game-owned facts/events remain authoritative; a queued line is not delivered knowledge. Record whether a line was queued, began, completed or was interrupted, and decide what may be repeated after cancellation. This is a design contract, not a new runtime architecture.

For each intended line, name its purpose, triggering evidence, knowledge boundary, priority, expiry, interruption behavior and silent/text fallback. Silence can preserve discovery; avoid explaining an inference before the player can observe it. Keep fictional identity and rights separate from provider voice identifiers.

Original worked choice: a guide has a low-priority observation queued when a hazard appears. Expire that observation, deliver the short urgent warning, and do not automatically replay stale chatter afterward. Ask in playtesting whether the warning helped action and whether interruption felt coherent. File speech generation supplies an asset; latency, cancellation, buffering and live transport need a separately authorized implementation and runtime review.

Design basis: [Patrick Ewing and William Armstrong, Do You Copy? The dialog system in Firewatch](https://media.gdcvault.com/gdc2017/Presentations/Armstrong_Do_you_copy.pdf) and [Emily Short, Bowls of Oatmeal and Text Generation](https://emshort.blog/2016/09/21/bowls-of-oatmeal-and-text-generation/). The worked interruption policy is a proposed application, not a claim that a particular companion architecture has been validated.
