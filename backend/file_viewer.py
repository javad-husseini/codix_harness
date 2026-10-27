"""Read-only user viewing, independent of agent approval tickets."""
from backend.policy import category, redact, relative_path


class FileViewer:
    def __init__(self, gateway):
        self.gateway = gateway

    def read(self, project_id, path):
        path = relative_path(path)
        if category(path) == 'secret':
            raise PermissionError('Secret files cannot be displayed in the file viewer.')
        result = self.gateway.file(project_id, {'op': 'view', 'path': path})
        if 'content' in result:
            result['content'] = redact(result['content'])
        return {'path': path, **result}
