from parser.Parser import LL1Parser

"""
sealed aether id = insc_lit;
inscription id = insc_lit;
circle id {
    aura id;
};
cast(insc_lit);
"""

tokens = [
    "grimoire",
    "(",
    ")",
    "{",
    "cast",
    "(",
    "insc_lit",
    ")",
    ";",
    "inscription",
    "id",
    "=",
    "insc_lit",
    ";",
    "}"
]

result = LL1Parser().parse(tokens)

print("Valid:", result.valid)
if result.error:
    print("Error:", result.error, "at", result.line, result.column)

for step in result.steps:
    print(step.action)
