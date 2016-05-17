import configparser

config = configparser.ConfigParser()
config.read("./config.ini")

## Config helper
def configSectionMap(section):
    dict1 = dict(config.items(section))
    return dict1