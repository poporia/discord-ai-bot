import re
from janome.tokenizer import Tokenizer
import discord




gtoken = Tokenizer("./libs/dic/user_dic.csv", udic_type="simpledic", udic_enc="utf8")


def gomamayo(text):
    text = re.sub(r'\[|\]|\(|\)|「|」', '。', text)
    wlist = []
    #トークン処理(未知語は reading が None になるため表層形で代用)
    for token in gtoken.tokenize(text):
        wlist.append((token.reading or token.surface,token.surface,token.part_of_speech.split(',')[0]))
    step = goma1v1(wlist)
    gomalist = gomajoin(step)
    return totable(gomalist)
                     
def goma1v1(wlist):
    step1 = []
    for i in range(0,len(wlist) - 1):
        tmp = find(wlist[i], wlist[i+1])
        if tmp is not None:
            step1.append((i, i+1) + tmp)
    return step1

def find(tup1,tup2):
    result = None
    th = re.compile(r'記号|助詞|助動詞')
    if bool(th.search(tup1[2])) or bool(th.search(tup2[2])):
        return result
    else:
        for i in range(1,len(tup1[0]) + 1):
            tmp1 = tup1[0][-i:]
            tmp2 = tup2[0][:i]
            if tmp1 == tmp2:
                result = (i, tup1[1], tup2[1])
    return result

def gomajoin(step1):
    result = []
    for  word in step1:
        if not result:
            result.append(word)
        else:
            if word[0] == result[-1][1]:
                result[-1] = (result[-1][0], word[1], max(word[2],result[-1][2]), result[-1][3] + result[-1][4], word[4])
            else:
                result.append(word)
    return result



def totable(tlist):
    # (次数, ゴママヨ発生区間) のリストを返す(旧pandas表の代替・軽量)
    rows = []
    for goma in tlist:
        size = goma[1] - goma[0] - 1
        if size > 2:
            size = 2
        rows.append((goma[2], goma[3] + goma[4]))
    rows.sort(key=lambda r: r[0])
    return rows or None


def goma_em(rows)->"discord.Embed|None":
        if rows:
            embed = discord.Embed(title = "ゴママヨ found!!!")
            for count, span in rows:
                embed.add_field(name=str(count)+"次",value=span,inline=False)
            return embed
        else:
            return None


#debug
#text = "メガガイア跡地"
#print(gomamayo(text))
