import httplib2
import urllib
from BeautifulSoup import BeautifulSoup
import re
import commands
import cgi
from pprint import pprint as pp

# VERSIONONE URLS
BASE_VO_URL = "https://www15.v1host.com/NTTMCL/VersionOne/rest-1.v1/Data/"
TEST_CASE_VO_URL = BASE_VO_URL + "Test"
DEFECT_VO_URL = BASE_VO_URL + "Defect"

# Test Statuses
PASSED_VO = 'TestStatus:129'
FAILED_VO = 'TestStatus:155'

# Test Types
AUTOMATED_VO = 'TestCategory:1698'

HTML_TAG_REG = re.compile(r'<.*?>')
TC_RELATION_REG = re.compile(r'idref="\w+:\w+"')

def html_encoder(str):
    return cgi.escape(str).replace(' ','%20')

def html_decoder(str):
    return BeautifulSoup(str,convertEntities=BeautifulSoup.HTML_ENTITIES)

def url_encoder(str):
    return urllib.urlencode({'{0}'.format(str): ''})

def remove_html_tags(data):
    return HTML_TAG_REG.sub('', str(data))

def change_test_result(html, headers, tcid, passed):
    status_xml = '<Relation name="Status" act="set">\
                    <Asset idref="{status}"/>\
                  </Relation>'.format(status=PASSED_VO if passed else FAILED_VO)
    resp, content = html.request(TEST_CASE_VO_URL+"/{tcid}".format(tcid=tcid), 
                                "POST", 
                                headers=headers, 
                                body='<Asset>{relation}</Asset>'\
                                    .format(relation=status_xml))
    print content

def change_test_category(html, headers, tcid, category):
    if category == 'Automated':
        category_vo = AUTOMATED_VO
    else:
        category_vo = ''
    category_xml = '<Relation name="Category" act="set">\
                        <Asset idref="{category}"/>\
                    </Relation>'.format(category=category_vo)
    resp, content = html.request(TEST_CASE_VO_URL+"/{tcid}".format(tcid=tcid), 
                                "POST", 
                                headers=headers, 
                                body='<Asset>{relation}</Asset>'\
                                    .format(relation=category_xml))
    print content

def update_actual_result_for_tc(html, headers, tcid, result):
    result_xml = '<Attribute name="ActualResults" act="set">{result}'\
                 '</Attribute>'.format(result=result)
    resp, content = html.request(TEST_CASE_VO_URL+"/{tcid}".format(tcid=tcid), 
                                "POST", 
                                headers=headers, 
                                body='<Asset>{result}</Asset>'\
                                    .format(result=result_xml))
    print content
                    
def create_object(URL, html, headers, attr_params, rel_params):
    xml = ''
    if attr_params:
        for attr,value in attr_params.items():
            xml += '<Attribute name="{0}" act="set" >{1}'\
                          '</Attribute>'.format(attr,value)
    if rel_params:
        for rel,value in rel_params.items():
            if rel == 'Owners':
                # For multi-value relation, need to use act="add" or
                # act="remove" inside <Asset idref=... />
                xml += '<Relation name="{0}" >'\
                              '<Asset act="add" idref="{1}" />'\
                              '</Relation>'.format(rel,value)
            else:
                xml += '<Relation name="{0}" act="set" >'\
                              '<Asset idref="{1}"/>'\
                              '</Relation>'.format(rel,value)

    pp(xml)
    print ''
    resp, content = html.request(URL,
                                "POST",
                                headers=headers,
                                body='<Asset>{0}</Asset>'.format(xml))
    print content

def format_to_html(str):
    result = html_encoder('<p>')
    str_tokens = str.split('\n')
    for str_token in str_tokens:
        result += str_token + html_encoder('<br/>')
    result += html_encoder('</p>')
    return result

html = httplib2.Http(".cache")
html.add_credentials('admin', 'admin')
resp, content = html.request(BASE_VO_URL, "GET")
headers = {'Cookie': resp['set-cookie'], 
            'Content-type': 'text/xml; charset=utf-8'}
#print headers

# get all test cases
resp, content = html.request(TEST_CASE_VO_URL, "GET", headers=headers)

#pp(content)

tcs = content.split('Data/Test/')
for tc in tcs:
    bs = BeautifulSoup(tc)
    category = bs.find(name='attribute',attrs={'name':'Category.Name'})
    if category:
        # Only pick Automated test cases
        if category.text == 'Automated':
            tcid = tc.split('" id=')[0]
            att_tokens = bs.findAll('attribute')
            attrs_dict = {}
            for att_token in att_tokens:
                attrs_dict[att_token['name']] = \
                    remove_html_tags(html_decoder(att_token.text))
                print '{name}: "{text}"'.format(name=att_token['name'],
                        text=attrs_dict[att_token['name']])

            # Execute test steps
            steps = attrs_dict['Steps'].split('\n')
            tc_passed = True
            tc_actual_output = ''
            for step in steps:
                if step:
                    print step
                    status, output = commands.getstatusoutput(step)
                    print (status, output)
                    tc_actual_output += 'Output for step {0}:\n{1}\n'\
                                            .format(step, output)
                    if status != 0:
                        tc_passed = False
            
            # Export test result to VO
            update_actual_result_for_tc(html, headers, tcid,
                                        format_to_html(tc_actual_output))
            # Assign test result
            change_test_result(html, headers, tcid, tc_passed)

            rel_tokens = bs.findAll('relation')
            idref_dict = {'Scope':'',
                          'Timebox':'',
                          'Team':'',
                          'Theme':'',
                          'Member':''}
            idrefs = TC_RELATION_REG.findall(str(rel_tokens))
            for idref in idrefs:
                idref_tokens = idref.replace('idref=','')\
                                    .replace('"','').split(':')
                idref_dict[idref_tokens[0]] = '{0}:{1}'.format(idref_tokens[0],
                                                                idref_tokens[1])
            #print '\n'
            #pp(idref_dict)

            if not tc_passed:
                desc = '\nSteps to reproduce:\n{0}\n'.format(attrs_dict['Steps'])
                desc += '\nExpected result:\n{0}\n'\
                        .format(attrs_dict['ExpectedResults'])
                desc += '\nActual result:\n{0}\n'.format(tc_actual_output)
                attr_params = {'Name':'Failed test case: {0}'\
                                            .format(attrs_dict['Name']),
                               'Description': format_to_html(desc)}

                rel_params = {'Scope':idref_dict['Scope'] , # Project
                              'Timebox':idref_dict['Timebox'], #Iteration/Sprint
                              'Team':idref_dict['Team'],
                              'Parent':idref_dict['Theme'],
                              'Owners':idref_dict['Member'],
                            }
                #pp(attr_params)
                #pp(rel_params)

                create_object(DEFECT_VO_URL,html,headers,attr_params,rel_params)
            print '\n\n'


#attr_params = {'Name':'Testing creation test case from api'}
#rel_params = {'Parent':'Story:1077',
#              'Owners':'Member:20',
#             }
#create_object(TEST_CASE_VO_URL,html,headers,attr_params,rel_params)

