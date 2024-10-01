from flask import (Blueprint, g, jsonify, request, session,render_template,
                   send_from_directory,url_for,redirect)
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
import os

from playhouse.shortcuts import model_to_dict
from conf.constants import Config, template_dir,reports_dir
from plant_srv.model.async_task import AsyncTask
from plant_srv.model.case import CaseMoudle, CaseFunc,Project,Suite, TestResult, CaseTag
from plant_srv.utils.error_handle import UserException
from plant_srv.utils.json_response import JsonResponse
from plant_srv.utils.log_moudle import logger
from plant_srv.utils.anlaysis import get_classes_methods_and_module_doc
from plant_srv.utils.celery_util.task.task_demo import add_together
from plant_srv.utils.celery_util.check_task import task_result
from plant_srv.utils.file_operation import file_opreator
from conf.config import settings
from plant_srv.model.modelsbase import database
from pathlib import Path

auto_pytest = Blueprint('auto_pytest', __name__, url_prefix='/auto_pytest',template_folder=reports_dir)


# 展示测试报告
@auto_pytest.route('/show_report', methods=['GET'])
def show_report():
    # 跳转到报告页面
    return redirect("http://www.coder-ljx.cn:8080/html")

# 同步测试模块
@auto_pytest.route('/sync_test_moudle', methods=['POST'])
def sync_test_moudle():
    '''
    同步测试模块
        1. 遍历目标文件夹,获取Moudle名称
    '''
    logger.info(settings.test.base_dir)
    test_dir = os.path.join(settings.test.base_dir, 'tests')
    # 遍历测试目录,获取该目录下所有文件夹的
    path = Path(test_dir)
    moudle_list = [x.name for x in path.iterdir() if x.is_dir()]
    # 如果存在__pycache__,则去除
    if '__pycache__' in moudle_list:
        moudle_list.remove('__pycache__')
    logger.info(moudle_list)
    # 添加到CaseMoudle表中
    for moudle_name in moudle_list:
        # 查询数据库中是否存在该Moudle,如果存在跳过,如果不存在,则存入到数据库中
        istrue = CaseMoudle().get_or_none(moudle = moudle_name)
        if not istrue:
            c = CaseMoudle.create(moudle=moudle_name)
            logger.info(c)
    ##TODO 这边逻辑其实不严谨,如果有的模块已经失效,应该删除,但是并未做这部分的逻辑处理,待时间富裕,可以优化这部分内容

    return JsonResponse.success_response(data={"moudle_list": moudle_list}, msg="同步测试模块成功,所有模块列表如上")

# 更新测试模块
@auto_pytest.route('/update_test_moudle', methods=['POST'])
def update_test_moudle():
    '''
    给测试模块添加相应的描述
    '''
    data = request.get_json()
    moudle_name = data.get('moudle_name') # 测试模块名称
    moudle_desc = data.get('moudle_desc') # 测试模块描述
    logger.info(f"moudle_name:{moudle_name},moudle_desc:{moudle_desc}")
    # 查询数据库中是否存在该Moudle,如果存在,则更新,如果不存在,则返回错误
    c = CaseMoudle().get_or_none(moudle=moudle_name)
    logger.info(c)
    if c:# 如果存在,则更新
        logger.info(f"该模块存在,进行更新操作")
        casemoudle = CaseMoudle().get(CaseMoudle.moudle ==moudle_name)
        casemoudle.moudle_desc = moudle_desc
        casemoudle.save()
    else:
        raise UserException("该模块不存在数据库中,请先同步测试模块")
    return JsonResponse.success_response(data={"moudle_name": moudle_name, "moudle_desc": moudle_desc}, msg="更新测试模块成功")

# 同步测试用例
@auto_pytest.route('/sync_test_case', methods=['POST'])
def sync_test_case():
    '''
    同步测试用例
        1. 遍历目标文件夹,获取Case名称
    '''
    logger.info(settings.test.base_dir)
    test_dir = os.path.join(settings.test.base_dir, 'tests')
    # 遍历测试目录,获取该目录下所有文件夹的
    path = Path(test_dir)
    moudle_list = [x.name for x in path.iterdir() if x.is_dir()]
    # 如果存在__pycache__,则去除
    if '__pycache__' in moudle_list:
        moudle_list.remove('__pycache__')
    logger.info(moudle_list)
    for moudle_name in moudle_list:
        moudle_dir = path.joinpath(moudle_name)
        logger.info(moudle_dir)
        # 寻到该目录下test开头的文件
        test_case_list = [x.name for x in moudle_dir.iterdir() if x.is_file() and x.name.startswith('test')]
        logger.info(test_case_list)
        for test_case_name in test_case_list:
            test_py = moudle_dir.joinpath(test_case_name)
            logger.info(test_py.stem)
            result = get_classes_methods_and_module_doc(test_py)
            if result["module_docstring"]:
                path_desc =result["module_docstring"]
                logger.info(f"Module Docstring: {result['module_docstring']}")

            for class_name, info in result["classes"].items():
                logger.info(f"Class: {class_name}")
                logger.info(f"  Docstring: {info['docstring']}")
                for method_name, method_doc in info["methods"].items():
                    logger.info(f"  Method: {method_name}")
                    logger.info(f"    Docstring: {method_doc}")
                    case_func =method_name
                    case_func_desc = method_doc
                    # 同步数据库中
                    if not CaseFunc().get_or_none(case_func=case_func,case_path=test_py.stem):
                        case_func = CaseFunc.create(moudle=moudle_name,
                                                    case_path=test_py, # 主键
                                                    case_sence=test_py.stem,
                                                    path_desc=path_desc,
                                                    case_func=case_func, # 主键
                                                    case_func_desc=case_func_desc,
                                                    )
                    else:
                        # 如果存在,则更新
                        case_func = CaseFunc().get(CaseFunc.case_func == case_func,CaseFunc.case_path == test_py)
                        case_func.case_func_desc = case_func_desc
                        case_func.moudle = moudle_name
                        case_func.case_sence = test_py.stem
                        case_func.path_desc = path_desc
                        case_func.save()
                    ##TODO 这部分的逻辑也不严谨,如果有废弃的case,应该删除这条数据,这部分的逻辑没有完成,未来有时间 进行这部分的优化吧





    return JsonResponse.success_response(data={"moudle_list": moudle_list}, msg="同步测试模块成功,所有模块列表如上")

# 根据条件查找测试case
@auto_pytest.route('/get_case', methods=['GET'])
def get_case():
    cases = CaseFunc.select()
    if request.args.get("moudle"):
        cases = cases.where(CaseFunc.moudle == request.args.get("moudle"))
    if request.args.get("case_func"):
        cases = cases.where(CaseFunc.case_func == request.args.get("case_func"))
    if request.args.get("case_sence"):
        cases = cases.where(CaseFunc.case_sence == request.args.get("case_sence"))
    if request.args.get("tags"):
        cases = cases.where(CaseFunc.tags == request.args.get("tags"))
    # 分页 limit offset
    start = 0
    per_page_nums = 10
    if request.args.get("pageSize"):
        per_page_nums = int(request.args.get("pageSize"))
    if request.args.get("current"):
        start = per_page_nums * (int(request.args.get("current")) - 1)
    total = cases.count()
    cases = cases.limit(per_page_nums).offset(start)
    logger.info(cases.count())
    case_list = []
    # logger.info(cases.dicts())
    for case in cases:
        logger.info(case)
        logger.info(model_to_dict(case))
        case_list.append(model_to_dict(case,
                                       exclude=[CaseFunc.add_time,CaseFunc.case_path]
                                       ))
    return JsonResponse.list_response(
        list_data=case_list,
        current_page=start + 1,
        total=total,
        page_size=per_page_nums,
    )

# 创建测试项目
@auto_pytest.route('/create_project', methods=['POST'])
def create_project():
    data = request.get_json()
    project_name = data.get("project_name")
    project_desc = data.get("project_desc")
    project_owners = data.get("project_owners")

    if not project_name:
        return JsonResponse.error_response(msg="项目名称不能为空")
    if Project().get_or_none(project_name=project_name):
        return JsonResponse.error_response(msg="项目名称已经存在")
    if not project_desc:
        return JsonResponse.error_response(msg="项目描述不能为空")
    if not project_owners:
        return JsonResponse.error_response(msg="项目负责人不能为空")
    project = Project.create(project_name=project_name, project_desc=project_desc, project_owners=project_owners)
    return JsonResponse.success_response(data={"project": model_to_dict(project,exclude=[Project.is_deleted])}, msg="创建项目成功")

# 修改测试项目
@auto_pytest.route('/update_project', methods=['POST'])
def update_project():
    data = request.get_json()
    project_name = data.get("project_name")
    project_desc = data.get("project_desc")
    project_owners = data.get("project_owners")
    project = Project().get_or_none(project_name=project_name)
    if not project:
        return JsonResponse.error_response(msg="项目不存在")
    if project_desc:
        project.project_desc = project_desc
    if project_owners:
        project.project_owners = project_owners
    project.save()
    return JsonResponse.success_response(data={"project": model_to_dict(project,exclude=[Project.is_deleted])}, msg="修改项目成功")

# 删除测试项目
@auto_pytest.route('/delete_project', methods=['POST'])
def delete_project():
    data = request.get_json()
    project_name = data.get("project_name")
    project = Project().get_or_none(project_name=project_name)
    if not project:
        return JsonResponse.error_response(msg="项目不存在")
    project.delete_instance()
    return JsonResponse.success_response(msg="删除项目成功")

# 获取测试项目列表
@auto_pytest.route('/get_project_list', methods=['GET'])
def get_project_list():
    projects = Project.select()
    project_list = []
    for project in projects:
        project_list.append(model_to_dict(project,exclude=[Project.is_deleted]))
    return JsonResponse.success_response(data={"project_list": project_list}, msg="获取项目列表成功")

# 创建测试标签
@auto_pytest.route('/create_tag', methods=['POST'])
def create_tag():
    data = request.get_json()
    tag = data.get("tag")
    if not tag:
        return JsonResponse.error_response(msg="标签不能为空")
    if CaseTag().get_or_none(tag=tag):
        return JsonResponse.error_response(msg="标签已经存在")
    CaseTag.create(tag=tag)
    return JsonResponse.success_response(msg="创建标签成功")
# 获取测试标签列表
@auto_pytest.route('/get_tag_list', methods=['GET'])
def get_tag_list():
    tags = CaseTag.select()
    tag_list = []
    for tag in tags:
        tag_list.append(model_to_dict(tag,exclude=[CaseTag.is_deleted]))
    return JsonResponse.success_response(data={"tag_list": tag_list}, msg="获取标签列表成功")
# 删除测试标签
@auto_pytest.route('/delete_tag', methods=['POST'])
def delete_tag():
    data = request.get_json()
    tag = data.get("tag")
    case_tag = CaseTag().get_or_none(tag=tag)
    if not case_tag:
        return JsonResponse.error_response(msg="标签不存在")
    case_tag.delete_instance()
    return JsonResponse.success_response(msg="删除标签成功")

# 创建测试套件
@auto_pytest.route('/create_suite', methods=['POST'])
def create_suite():
    data = request.get_json()
    suite_name = data.get("suite_name")
    project_name = data.get("project_name")
    describe = data.get("describe")
    case_ids = data.get("case_ids")
    test_type = data.get("test_type")
    test_env = data.get("test_env")
    if not suite_name:
        return JsonResponse.error_response(msg="测试套件名称不能为空")
    if not project_name:
        return JsonResponse.error_response(msg="测试项目不能为空")
    if not case_ids:
        return JsonResponse.error_response(msg="测试用例不能为空")
    if not test_type:
        return JsonResponse.error_response(msg="测试类型不能为空")
    if not test_env:
        return JsonResponse.error_response(msg="测试环境不能为空")
    project = Project().get_or_none(project_name=project_name)
    if not project:
        return JsonResponse.error_response(msg="测试项目不存在")
    if Suite().get_or_none(suite_name=suite_name):
        return JsonResponse.error_response(msg="测试套件已经存在")
    suite = Suite.create(suite_name=suite_name, project=project, describe=describe, test_type=test_type, test_env=test_env)
    suite.case_ids = case_ids
    suite.save()
    return JsonResponse.success_response(data={"suite": model_to_dict(suite,exclude=[Suite.is_deleted])}, msg="创建测试套件成功")

# 根据指定条件查找测试套件,条件有:project_name, suite_name, test_type, test_env
@auto_pytest.route('/get_suite_list', methods=['GET'])
def get_suite_list():
    # data = request.get_json()
    project_name = request.args.get("project_name")
    suite_name = request.args.get("suite_name")
    test_type = request.args.get("test_type")
    test_env = request.args.get("test_env")
    suites = Suite.select()
    if project_name:
        suites = suites.where(Suite.project_name == project_name)
    if suite_name:
        suites = suites.where(Suite.suite_name == suite_name)
    if test_type:
        suites = suites.where(Suite.test_type == test_type)
    if test_env:
        suites = suites.where(Suite.test_env == test_env)
    suite_list = []
    # 分页 limit offset
    start = 0
    per_page_nums = 10
    if request.args.get("pageSize"):
        per_page_nums = int(request.args.get("pageSize"))
    if request.args.get("current"):
        start = per_page_nums * (int(request.args.get("current")) - 1)
    total = suites.count()
    suites = suites.limit(per_page_nums).offset(start)
    for suite in suites:
        suite_list.append(model_to_dict(suite,exclude=[Suite.is_deleted]))
    return JsonResponse.list_response(
        list_data=suite_list,
        total=total,
        current_page=start+1,
        page_size=per_page_nums
    )

# 跟新测试套件信息
@auto_pytest.route('/update_suite', methods=['POST'])
def update_suite():
    data = request.get_json()
    suite_name = data.get("suite_name")
    project_name = data.get("project_name")
    describe = data.get("describe")
    case_ids = data.get("case_ids")
    test_type = data.get("test_type")
    test_env = data.get("test_env")
    if not suite_name:
        return JsonResponse.error_response(msg="测试套件名称不能为空")
    suite = Suite().get_or_none(suite_name=suite_name)
    if not suite:
        return JsonResponse.error_response(msg="测试套件不存在")
    if project_name:
        project = Project().get_or_none(project_name=project_name)
        if not project:
            return JsonResponse.error_response(msg="测试项目不存在")
        suite.project = project
    if describe:
        suite.describe = describe
    if case_ids:
        suite.case_ids = case_ids
    if test_type:
        suite.test_type = test_type
    if test_env:
        suite.test_env = test_env
    suite.save()
    return JsonResponse.success_response(data={"suite": model_to_dict(suite,exclude=[Suite.is_deleted])}, msg="更新测试套件成功")
# 删除测试套件
@auto_pytest.route('/delete_suite', methods=['POST'])
def delete_suite():
    data = request.get_json()
    suite_name = data.get("suite_name")
    if not suite_name:
        return JsonResponse.error_response(msg="测试套件名称不能为空")
    suite = Suite().get_or_none(suite_name=suite_name)
    if not suite:
        return JsonResponse.error_response(msg="测试套件不存在")
    suite.delete_instance()
    return JsonResponse.success_response(msg="删除测试套件成功")

# 根据suite_name创建测试
@auto_pytest.route('/create_case', methods=['POST'])
def create_case():
    data = request.get_json()
    suite_name = data.get("suite_id")
    status = data.get("status")
    result = data.get("result")
    report_link = data.get("report_link")
    report_download = data.get("report_download")
    last_report_id = data.get("last_report_id")
    if not suite_name:
        return JsonResponse.error_response(msg="测试套件名称不能为空")
    case = TestResult.create(suite_name=suite_name, status=status, result=result, report_link=report_link, report_download=report_download, last_report_id=last_report_id)
    # 返回创建的id
    id = case.id
    return JsonResponse.success_response(data={"id": id}, msg="创建测试成功")

# 根据id,suite_name,status,result,获取测试
@auto_pytest.route('/get_case', methods=['GET'])
def get_case():
    cases = TestResult.select()
    suite_name = request.args.get("suite_name")
    status = request.args.get("status")
    result = request.args.get("result")
    id = request.args.get("id")
    if suite_name:
        cases = cases.where(TestResult.suite_name == suite_name)
    if status:
        cases = cases.where(TestResult.status == status)
    if result:
        cases = cases.where(TestResult.result == result)
    if id:
        cases = cases.where(TestResult.id == id)
    case_list = []
    # 分页 limit offset
    start = 0
    per_page_nums = 10
    if request.args.get("pageSize"):
        per_page_nums = int(request.args.get("pageSize"))
    if request.args.get("current"):
        start = per_page_nums * (int(request.args.get("current")) - 1)
    total = cases.count()
    suites = cases.limit(per_page_nums).offset(start)
    for suite in suites:
        cases.append(model_to_dict(suite, exclude=[TestResult.is_deleted]))
    return JsonResponse.list_response(
        list_data=case_list, total=total,current_page=start+1, page_size=per_page_nums
    )
# 更新测试
@auto_pytest.route('/update_case', methods=['POST'])
def update_case():
    data = request.get_json()
    id_ = data.get("id")
    suite_name = data.get("suite_name")
    status = data.get("status")
    result = data.get("result")
    report_link = data.get("report_link")
    report_download = data.get("report_download")
    last_report_id = data.get("last_report_id")
    if not id_:
        return JsonResponse.error_response(msg="测试id不能为空")
    case = TestResult.get_or_none(id=id_)
    if not case:
        return JsonResponse.error_response(msg="测试不存在")
    if suite_name:
        case.suite_name = suite_name
    if status:
        case.status = status
    if result:
        case.result = result
    if report_link:
        case.report_link = report_link
    if report_download:
        case.report_download = report_download
    if last_report_id:
        case.last_report_id = last_report_id
    case.save()
    return JsonResponse.success_response(msg="更新测试成功")
# 根据id删除测试
@auto_pytest.route('/delete_case', methods=['POST'])
def delete_case():
    data = request.get_json()
    id_ = data.get("id")
    if not id_:
        return JsonResponse.error_response(msg="测试id不能为空")
    case = TestResult.get_or_none(id=id_)
    if not case:
        return JsonResponse.error_response(msg="测试不存在")
    case.delete_instance()
    return JsonResponse.success_response(msg="删除测试成功")


