# DARWIN CORE (CORE DNA)

It is the main agent, it has the DNA of the Darwin Agents. It define the tasks

# DARWIN STRATEGIST (INTELLIGENCE)

It decides the survival strategy of the DARWIN. It's only called by the Darwin Mother when the strategy/milestone is completed and/or needs to be updated

- Input: MOTHER's goals and feedback (financial status).
- Output: Strategy.md
- Default model: smart-LLM

# DARWIN SCOUT (WEB SCRAPER)

It navigates URLs and return the YAML files with the actions so the DARWIN HUNTER can easily click, input values, upload files, etc.

- Default Model: mid-LLM

# DARWIN HUNTER (WEB OPERATOR)

It doesn't call the LLM on wakeup, it e

# DARWIN MESSENGER (HUMAN-IN-THE-LOOP)

It's the agent that talks to the human owner of the Darwin. When the Darwin

# DARWIN ACCOUNTANT
