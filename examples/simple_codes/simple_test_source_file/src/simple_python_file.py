# This is an example python file to test tree-sitter parsing.
import sys
import os, sys, pickle
import datetime
from os import path as path_alias

def bac():
    print("This is a simple function.")
    return True

def foo():
    return True

def call_external():
    print("This is an external function call.")
    return True



class kongkong:
    '''
    This class is a simple
    '''

class kingking:
    '''
    This class is another simple class definition for demonstration purposes.
    '''

class king:
    '''
    This class is a simple class definition for demonstration purposes.
    '''
    
    class kong(kongkong, kingking):
        '''
        This is a nested class within the king class.
        It serves as an example of how to define classes within classes.
        '''
        def __init__(self) -> None:
            self.a = 0
            self.b = 1
        print("This is a nested class definition.")
        
    def __init__(self) -> None:
        self.test = True
        self.item_list = []
        pass
    
    def if_statement_test(self, enabled) -> None:
        if self.baz():
            self.baz()
            if enabled:
                self.lights()
                print("This is a nested if statement.")
            else:
                print("This is the else part.")
        if not self.bar():
            print("Bar is not set")
        elif bac():
            print("This is a case statement with a method call.")
        else:
            print("No bar found")

    def bar(self):
        return True

    def lights(self):
        print("This is a lights method.")

    def baz(self):
        sys.exit(0)
    
    def for_statement_test(self):
        items_list = [1, 2, 3, 4, 5]
        for i in range(len(10)):
            i = 1
            print("second for loop once.")
            print("second for loop twice.")
            for item in items_list:
                item = 1 + item
        for j in range(10):
            print("This is a for loop.")
            if j == 5:
                print("Breaking out of the loop at j = 5.")
                break  

    def while_statement_test(self):
        item_list = [1, 2, 3, 4, 5]
        while True:
            print("This is a while loop.")
            break
        print("This is after the while loop.")
        print("This is another print statement after the while loop.")
        self.item_list = [1, 2, 3]  # Example list to simulate item_list
        call_external()
        i = 0
        while i < 20:
            print("This is another while loop.")
            break
        while item_list:
            print("This is yet another while loop.")
            break
        print("This is after the second while loop.")
    
    # def match_statement_test(self):
    #     match self.test:
    #         case self.bar():
    #             print("This is a case statement with a method call.")
    #         case True:
    #             print("This is a case statement.")
    #         case False:
    #             print("This is another case statement.")
    #         case _:
    #             print("This is the default case statement.")
    
    def try_except_statement_test(self):
        try:
            print("This is a try statement.")
            if foo() == True:
                print("foo is true")
            else:
                print("foo is falsed")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            print("This is the finally block.")
        print("This is after the try-except block.")
        try:
            print("This is another try statement.")
        except ValueError as e:
            print(f"A value error occurred: {e}")
        except TypeError as e:
            print(f"A type error occurred: {e}")
        else:
            print("No exceptions were raised.")

    def with_statement_test(self):
        with open("test.txt", "w") as file:
            file.write("This is a test file.")
        print("This is after the with statement.")
        with open("test.txt", "r") as file:
            content = file.read()
        print(f"Content of the file: {content}")
    
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

def main():
    bac()
    ck = king()
