class LexerError(Exception):
    def __init__(self, message: str, line: int, column: int, skip_number: bool = False):
        super().__init__(f"Lexical Error [Line {line}, Col {column}: {message}]")
        self.message = message
        self.line = line
        self.column = column
        self.skip_number = skip_number