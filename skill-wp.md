#Metadata
name: Project reconnaissance
description: Go through a projects code and docummentation, understands it and creates A-Z handbook how to use it. Handy for frameworks and boilerplates.

#Overview
This skill reads whole code-base and all available docummentation in the repository and creates handbook application that can developer use to understand framework or boilerplate. It contains deep description of the code that is logically separated by code (framework) structure with handy examples that are derivated from the code itself. This application is intended for humans not for agents, however, it is readable for agents as well.

#Guardrails
Stands inside repository. If repository contains third party library mention its origin if possible and use internet for description of what it does.
All the files created by this skill are added to the .gitignore if not specified otherwise.

#Application design
- Application should have very simple design that contains from side panel located on the left-hand side of the page and the chapter content in the rest of the site.
- For each example include in the code block that have anchors to other parts of the application if necessary.
- Application is single html site.

#Skill output
Application are saved in the project root in the 'project-recon' directory that contains html file. In the root there is project-recon.lock file that can be used to regenerate the application easily without need to go through whole project again.
