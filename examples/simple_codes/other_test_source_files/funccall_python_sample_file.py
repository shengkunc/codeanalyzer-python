def outside_function():
    print("This is an outside function.")
    return True

class SampleClass:
    def if_statement_test(self, enabled) -> None:
        outside_function()
        if self.baz():
            self.baz()
            if enabled:
                self.lights()
                print("This is a nested if statement.")
            else:
                print("This is the else part.")
        if not self.bar():
            print("Bar is not set")
        elif self.bac():
            print("This is a case statement with a method call.")
        else:
            print("No bar found")
        self.baz()

    def baz(self):
        print("This is a baz method.")
        return True

    def lights(self):
        print("This is a lights method.")
        return True

    def bar(self):
        print("This is a bar method.")
        return True

    def bac(self):
        print("This is a bac function.")
        return True


sc = SampleClass()
sc.if_statement_test(True)
sc.if_statement_test(False)
sc.baz()
sc.lights()
sc.bar()
sc.bac()