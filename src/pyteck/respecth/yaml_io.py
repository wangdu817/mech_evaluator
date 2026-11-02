"""Scientific YAML keeps NO as a species while true/false remain booleans."""
import re
import yaml


class ScientificLoader(yaml.SafeLoader):
    pass


ScientificLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in rules if tag != 'tag:yaml.org,2002:bool']
    for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
ScientificLoader.add_implicit_resolver('tag:yaml.org,2002:bool',
    re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$'), list('tTfF'))


def load_yaml(text):
    return yaml.load(text, Loader=ScientificLoader)
