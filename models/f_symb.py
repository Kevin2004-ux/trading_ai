import numpy as np

def f_symb(z):
    # z[0]=SMA_50_slope, z[1]=Relative_Volume, etc.
    return (math.sin((-2.3440766*z[3] + z[9])/(z[3] + z[2]/(-1.7422537))) + 0.19945073)/z[9]
