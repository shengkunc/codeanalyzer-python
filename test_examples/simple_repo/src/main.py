from src.sub_folder1.module2 import Module2
from src.sub_folder1.module1 import Module1
from src.sub_folder1.module3 import add

a = 0
b = a + 1

def submain():
    a += 1
    b += 2
    return a, b

def main(arg1, arg2):
    module1 = Module1()
    module2 = Module2()
    c = add(6, 7) + module1.add(a, b)
    d = module2.minus(arg1, arg2)
    submain()
    print(a, b, c, d)


main(10, 5)


