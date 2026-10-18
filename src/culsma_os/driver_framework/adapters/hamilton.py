"""Hamilton compilation has a distinct result; never pretends to execute."""


class HamiltonCompilationAdapter:

    def __init__(self, compiler):
        self.compiler = compiler

    def compile(self, request):
        return self.compiler.compile(
            request.transfers, request.context, request.profile
        )
