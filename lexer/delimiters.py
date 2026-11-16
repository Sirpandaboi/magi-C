import string

LETTERS = set(string.ascii_letters)
NONZERO = set("123456789")
NUMBERS = set("0123456789")
ASCII = set(string.printable)
INSC_ASCII = ASCII - {'"', "\\", "\n", "\r"}
ID_CHAR = LETTERS | NUMBERS | {"_"}
NEWLINE = {"\n", "\r"}

MATH_OP = {"+", "-", "*", "/", "%"}
REL_OP = {"<", ">", "="}
AND_OR_OP = {"&", "|"}

SPACE_DEL = {" ", "\t", "\n", "\r", "#"}
PAREN_DEL = SPACE_DEL | {"(", "#"}
CURLY_DEL = SPACE_DEL | {"{", "#"}
TRANSFER_DEL = SPACE_DEL | {";", "#"}

OPEN_PAREN_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", ")", "~", "+", "-", "!",'"', "#"}
CLOSE_PAREN_DEL = MATH_OP | REL_OP | AND_OR_OP | SPACE_DEL | {")", "{", "}", "]", "!", ";", ",", ":", "#"}
OPEN_CURLY_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "{", "}", "~", "+", "-", "!", '"', "#"}
CLOSE_CURLY_DEL = LETTERS | SPACE_DEL | {"}", ";", ",", "#", None}
OPEN_BRACKET_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "+", "-", "#"}
CLOSE_BRACKET_DEL = MATH_OP | REL_OP | AND_OR_OP | SPACE_DEL | {")", "}", "[", "]", "!", ";", ",", ":", "#"}

NEG_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "+", "-", "#"}
MATH_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "#"}
CREMENT_DEL = LETTERS | SPACE_DEL | {")", "]", ";", ",", "#"}

REL_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "+", "-", "#"}
EQUALITY_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "+", "-", "!", '"', "#"}

LOG_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "+", "-", "!", "#"}
NOT_DEL = LETTERS | SPACE_DEL | {"(", "#"}

BASE_ASSIGN_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "{", "~", "+", "-", "!", '"', "#"}
ASSIGN_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "~", "+", "-", "#"}

TERMINATOR_DEL = LETTERS | NUMBERS | SPACE_DEL | {"}", "#"}
COMMA_DEL = LETTERS | NUMBERS | SPACE_DEL | {"(", "{", "~", "+", "-", "!", '"', "#"}
CONCAT_DEL = LETTERS | SPACE_DEL | {"(", '"', "#"}

ID_DEL = MATH_OP | REL_OP | AND_OR_OP | SPACE_DEL | {"(", ")", "{", "}", "[", "]", "!", ".", ";", ",", ":", "#"}
AETHER_LIT_DEL = MATH_OP | REL_OP | AND_OR_OP | SPACE_DEL | {")", "{", "}", "]", "!", ";", ",", "#"}
ESSENCE_LIT_DEL = MATH_OP | REL_OP | AND_OR_OP | SPACE_DEL | {")", "}", "!", ";", ",", "#"}
INSCRIPTION_LIT_DEL = AND_OR_OP | SPACE_DEL | {")", "{", "}", "=", "!", ";", ",", ":", "#"}
AURA_LIT_DEL = AND_OR_OP | SPACE_DEL | {")", "}", "=", "!", ";", ",", "#"}

COMMENT_DEL = LETTERS | NUMBERS | SPACE_DEL | MATH_OP | REL_OP | AND_OR_OP | {"(", ")", "{", "}", "[", "]", "~", "!", ".", ";", ",", ":", '"', "#"}


# Characters that can begin a token to resynchronize after an error
TOKEN_START = LETTERS | NUMBERS | MATH_OP | REL_OP | AND_OR_OP | {"~", "!", "(", ")", "{", "}", "[", "]", '"', ".", ";", ",", ":", "#"}
