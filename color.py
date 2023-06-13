import math


def hex_to_lab(hex_code):
    rgb = tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))
    xyz = rgb_to_xyz(rgb)
    lab = xyz_to_cielab(xyz)

    return lab


def rgb_to_xyz(rgb):
    var_r = (rgb[0] / 255)
    var_g = (rgb[1] / 255)
    var_b = (rgb[2] / 255)

    if var_r > 0.04045:
        var_r = ((var_r + 0.055) / 1.055) ** 2.4
    else:
        var_r = var_r / 12.92
    if var_g > 0.04045:
        var_g = ((var_g + 0.055) / 1.055) ** 2.4
    else:
        var_g = var_g / 12.92
    if var_b > 0.04045:
        var_b = ((var_b + 0.055) / 1.055) ** 2.4
    else:
        var_b = var_b / 12.92

    var_r *= 100
    var_g *= 100
    var_b *= 100

    x = var_r * 0.4124 + var_g * 0.3576 + var_b * 0.1805
    y = var_r * 0.2126 + var_g * 0.7152 + var_b * 0.0722
    z = var_r * 0.0193 + var_g * 0.1192 + var_b * 0.9505

    return x, y, z


def xyz_to_cielab(xyz):
    x_nat = xyz[0] / 95.047
    y_nat = xyz[1] / 100
    z_nat = xyz[2] / 108.883

    if x_nat > 0.008856:
        x_nat = pow(x_nat, 1 / 3)
    else:
        x_nat = (7.787 * x_nat) + (16 / 116)
    if y_nat > 0.008856:
        y_nat = pow(y_nat, 1 / 3)
    else:
        y_nat = (7.787 * y_nat) + (16 / 116)
    if z_nat > 0.008856:
        z_nat = pow(z_nat, 1 / 3)
    else:
        z_nat = (7.787 * z_nat) + (16 / 116)

    l_star = (116 * y_nat) - 16
    a_star = 500 * (x_nat - y_nat)
    b_star = 200 * (y_nat - z_nat)

    return l_star, a_star, b_star


def compare_delta_e_2000(lab1: tuple, lab2: tuple):
    l1, a1, b1 = lab1
    c1 = math.sqrt(a1 ** 2 + b1 ** 2)
    l2, a2, b2 = lab2
    c2 = math.sqrt(a2 ** 2 + b2 ** 2)
    c_bar = (c1 + c2) / 2

    g = 0.5 * (1 - math.sqrt(c_bar ** 7 / (c_bar ** 7 + 6103525625)))

    xa1 = (1 + g) * a1
    xa2 = (1 + g) * a2
    xc1 = math.sqrt(xa1 ** 2 + b1 ** 2)
    xc2 = math.sqrt(xa2 ** 2 + b2 ** 2)
    h1 = math.degrees(math.atan2(b1, xa1))
    h1 += (h1 < 0) * 360
    h2 = math.degrees(math.atan2(b2, xa2))
    h2 += (h2 < 0) * 360

    delta_l_dash = l2 - l1
    delta_c_dash = xc2 - xc1
    delta_h = 0.0

    if xc1 * xc2:
        if math.fabs(h2 - h1) <= 180:
            delta_h = h2 - h1
        elif h2 - h1 > 180:
            delta_h = (h2 - h1) - 360
        elif (h2 - h1) < -180:
            delta_h = (h2 - h1) + 360

    delta_h_dash = 2 * math.sqrt(xc1 * xc2) * math.sin(math.radians(delta_h) / 2.0)

    l_bar = (l1 + l2) / 2
    c_bar = (xc1 + xc2) / 2
    h_bar = h1 + h2

    if xc1 * xc2:
        if math.fabs(h1 - h2) <= 180:
            h_bar = (h1 + h2) / 2
        else:
            if (h1 + h2) < 360:
                h_bar = (h1 + h2 + 360) / 2
            else:
                h_bar = (h1 + h2 - 360) / 2

    t = 1 \
        - 0.17 * math.cos(math.radians(h_bar - 30)) \
        + 0.24 * math.cos(math.radians(2 * h_bar)) \
        + 0.32 * math.cos(math.radians(3 * h_bar + 6)) \
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))

    delta_theta = 30 * math.exp(-((h_bar - 275) / 25) ** 2)

    xrc = 2 * math.sqrt(c_bar ** 7 / (c_bar ** 7 + 6103525625))

    xsl = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    xsc = 1 + 0.045 * c_bar
    xsh = 1 + 0.015 * c_bar * t
    xrt = -xrc * math.sin(2 * math.radians(delta_theta))

    xkl, xkc, xkh = 1, 1, 1

    final_l = delta_l_dash / (xkl * xsl)
    final_c = delta_c_dash / (xkc * xsc)
    final_h = delta_h_dash / (xkh * xsh)

    delta = math.sqrt(final_l ** 2 + final_c ** 2 + final_h ** 2 + xrt * final_c * final_h)
    return delta


def compare_delta_cie(lab1: tuple, lab2: tuple):
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    # (x - y)^2 = x^2 + y^2 - 2xy
    # [ 2 ] [ 5 ]   [ a ] [ d ]                         [ a^2 + d^2 - 2ad ]
    # [ 3 ] [ 6 ] = [ b ] [ e ] = A, B, A^2 B^2 - 2AB = [  ]
    # [ 4 ] [ 7 ]   [ c ] [ f ]]                        [

    #  [ 2  3  4  ]
    #  [ 8  9  10 ] =
    #  [ 11 12 13 ]

    similarity = math.sqrt(pow(l1 - l2, 2) + pow(a1 - a2, 2) + pow(b1 - b2, 2))
    return similarity
