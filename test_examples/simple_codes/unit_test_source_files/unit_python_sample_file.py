import sys
def bac():
    print("This is a simple function.")
    return True

def foo():
    return True

def call_external():
    print("This is an external function call.")
    return True


class king:
    def bar(self):
        return True

    def lights(self):
        print("This is a lights method.")

    def baz(self):
        sys.exit(0)

    def expression_statement_test(self):
        a = 10
        b = 20
        c = a + b
        print(f"The sum of a and b is: {c}")
        self.bar()
        self.lights()
        self.baz()
        print("This is an expression statement test.")
        print("This is another expression statement test.")
        print("This is yet another expression statement test.")
        call_external()
        bac()
        foo()

call_external()