"""Project storage for independent workflows. The first tab is the v1 workflow."""

MAX_TABS = 4


def tab_count(project):
    return 1 + len(project.get('tabs', []))


def tab_steps(project, index):
    return project['steps'] if index == 0 else project['tabs'][index - 1]['steps']


def tab_name(project, index):
    return project.get('first_tab_name', '작업 1') if index == 0 else project['tabs'][index - 1]['name']


def tab_project(project, index):
    result = {key: value for key, value in project.items() if key != 'tabs'}
    result['steps'] = tab_steps(project, index)
    if index:
        for key in ('routes', 'ranges', 'repeat_enabled'):
            result.pop(key, None)
        tab = project['tabs'][index - 1]
        result['workflow_repeats'] = tab.get('workflow_repeats', 1)
        result['repeat_on_reappear'] = tab.get('repeat_on_reappear', False)
    return result


def validate_tabs(project):
    tabs = project.get('tabs', [])
    if not isinstance(tabs, list) or len(tabs) >= MAX_TABS:
        raise ValueError(f'작업 탭은 최대 {MAX_TABS}개입니다.')
    for tab in tabs:
        if not isinstance(tab, dict) or not isinstance(tab.get('steps'), list):
            raise ValueError('작업 탭의 단계 목록 오류')
    for index in range(tab_count(project)):
        try:
            name = tab_name(project, index)
        except KeyError:
            name = None
        if not isinstance(name, str) or not name.strip() or len(name) > 32:
            raise ValueError('작업 탭 이름은 1~32자로 입력하세요.')
        if index:
            tab = tabs[index - 1]
            count = tab.get('workflow_repeats', 1)
            if type(count) is not int or not 0 <= count <= 100000:
                raise ValueError('탭 반복 횟수 오류')
            if type(tab.get('repeat_on_reappear', False)) is not bool:
                raise ValueError('탭 재등장 설정 오류')
