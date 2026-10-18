# Gym sources

Read alongside [studio-gym](../SKILL.md). Studios rarely publish their gym layouts, so most room designs in this skill are recommended practice built on the sources below. Talk contents marked "abstract only" were read from the published summary, not the recording.

## Metrics zoos and greybox

- The Level Design Book, "Metrics": player metrics (measured) versus building metrics (chosen), a developer-only metrics zoo walked after every metrics change, world-aligned grid textures. https://book.leveldesignbook.com/process/blockout/metrics
- "Lessons from Suzy Cube: Measuring up" (Game Developer): clear, borderline and impossible jump bands; never build at exactly the maximum. https://www.gamedeveloper.com/design/lessons-from-suzy-cube-measuring-up
- Unreal Lyra sample: shipped gym maps per feature plugin (`L_ShooterGym`). https://dev.epicgames.com/documentation/en-us/unreal-engine/lyra-sample-game-in-unreal-engine
- Valve Developer Community, Alien Swarm Mapper's Reference: published player clearances and step limits. https://developer.valvesoftware.com/wiki/Alien_Swarm_Mapper's_Reference

## Automated gameplay tests

- Robert Masella, "Automated Testing of Gameplay Features in Sea of Thieves", GDC 2019: many fast actor tests in minimal worlds, fewer map-based integration tests each checking one behaviour, polling until a timeout rather than fixed waits, handling of intermittent failures. https://gdcvault.com/play/1026366/Automated-Testing-of-Gameplay-Features (slides: https://media.gdcvault.com/gdc2019/presentations/Masella_Robert_AutomatedTestingOf.pdf)
- Unreal Engine, Functional Testing and Ground Truth Data: test actors placed in maps, stored verified results compared on later runs. https://dev.epicgames.com/documentation/en-us/unreal-engine/functional-testing?application_version=4.27
- Unreal Engine, Gauntlet automation framework. https://dev.epicgames.com/documentation/en-us/unreal-engine/gauntlet-automation-framework-overview-in-unreal-engine
- Unity Test Framework play mode and performance tests. https://docs.unity3d.com/Manual/test-framework/course/LostCrypt/performance-tests.html
- GUT input sender and the accumulated-input timing issue. https://gut.readthedocs.io/en/latest/Mocking-Input.html
- Factorio Friday Facts #60: small-map integration tests and a stored game-state checksum compared after each test. https://factorio.com/blog/post/fff-60

## Audio

- Audiokinetic, "Footsteps Material Management using Wwise": surface type from a downward trace, a material switch per footstep event, on-screen surface debug, failures to register in packaged builds. https://blog.audiokinetic.com/footsteps-material-management-using-wwise-unreal-engine-4-unity-3d/
- Audiokinetic, Wwise Audio Lab: a spatial-audio test level with rooms of different sizes, an adjustable echo chamber, in-game A/B toggles and a repeatable test emitter on saved paths. https://www.audiokinetic.com/en/wwise-audio-lab

## Physics

- Godot, Using Jolt Physics: backend differences, including areas not detecting static bodies by default. https://docs.godotengine.org/en/stable/tutorials/physics/using_jolt_physics.html
- Unity, Continuous collision detection: sweep and speculative modes and the tunnelling and ghost-collision cases they leave. https://docs.unity3d.com/2022.1/Documentation/Manual/ContinuousCollisionDetection.html

## Traversal

- Doug Sheahan, "Concrete Jungle Gym: Building Traversal in Marvel's Spider-Man", GDC 2019 (abstract only). https://gdcvault.com/play/1026084/Concrete-Jungle-Gym-Building-Traversal
- "Don't mean a thing if you ain't got that swing" (Game Developer): anchor geometry metrics, release timing, camera roll and field of view. https://www.gamedeveloper.com/design/don-t-mean-a-thing-if-you-ain-t-got-that-swing-in-i-spider-man-i-
- "How Spider-Man 2's traversal physics sling a faster superhero fantasy" (Game Developer): input friction found in playtests. https://www.gamedeveloper.com/programming/how-spider-man-2-s-traversal-physics-sling-a-faster-superhero-fantasy
- Push Square interview on Attack on Titan: Wings of Freedom: ODM controls simplified from a fully manual scheme. https://www.pushsquare.com/news/2016/08/interview_talking_attack_on_titan_wings_of_freedom_with_koei_tecmo
- Chin Xiang Chong, "The Evolution of Rodeo in Titanfall", GDC 2017 (abstract only): climbing onto a much larger enemy. https://gdcvault.com/play/1024094/The-Evolution-of-Rodeo-in

No published numbers were found for ODM anchor radius, rope length or target assist, or for studio flight and vehicle test areas. The rooms for those are inferred practice.
