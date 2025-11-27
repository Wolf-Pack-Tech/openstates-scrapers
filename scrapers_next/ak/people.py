from dataclasses import dataclass
import re

from lxml.etree import Element
import lxml.html
from lxml.html import HtmlComment
import requests
import scrapelib
from spatula.pages import HtmlPage, HtmlListPage, SkipItem
from spatula.selectors import CSS
from spatula.sources import Source

from openstates.models import ScrapePerson
from openstates.models.people import PartyName, RoleType
from openstates.utils.scrape import decode_cf_email


@dataclass
class PartialPerson:
    list_url: str
    chamber: str


def format_address(original_address: str) -> str:
    return re.sub(" AK,", ", AK", original_address)


def get_detail(context: Element, label: str, extra_xpath: str = "") -> Element:
    return context.xpath(f".//strong[normalize-space(.)='{label}']{extra_xpath}")[0]


class LatestSource(Source):
    """
    Get the latest session URL
    """

    retries = 0

    def get_response(self, scraper: scrapelib.Scraper) -> requests.models.Response:
        self.url = "https://www.akleg.gov/basis/mbr_info.asp"
        resp = scraper.get(self.url)
        root = lxml.html.fromstring(resp.content)
        current_year = CSS("#year option:last-child").match_one(root).get("value")

        if not current_year:
            return resp

        self.url = f"{self.url}?session={current_year}"
        return scraper.get(self.url)


class PersonDetail(HtmlPage):
    example_source = "https://www.akleg.gov/basis/Member/Detail/34?code=ALR"

    def process_page(self):
        details_div = CSS(".bioright").match_one(self.root)

        leadership_title_nodes = CSS(".leadership_title").match(details_div, min_items=0)
        leadership_title = leadership_title_nodes[0].text_content() if leadership_title_nodes else ""
        if "Name Changed" in leadership_title:
            raise SkipItem("Duplicate page; name changed")

        name_raw = CSS(".formal_name").match_one(details_div).text_content()
        _title, given_name, family_name = name_raw.split(" ", 2)

        hashed_email = get_detail(details_div, "Email:", "/following::a[1]").get("href").split("#")[1]
        email = decode_cf_email(hashed_email)

        district = get_detail(details_div, "District:").tail.strip()
        party_text = get_detail(details_div, "Party:").tail.strip()
        party = {
            "Democrat": PartyName.DEM,
            "Republican": PartyName.REP,
            "Not Affiliated": PartyName.IND,
        }[party_text]

        image = CSS(".legpic").match_one(self.root).get("src")

        p = ScrapePerson(
            name=f"{given_name} {family_name}",
            state="ak",
            party=party,
            district=district,
            chamber=self.input.chamber,
            image=image,
            email=email,
            given_name=given_name,
            family_name=family_name,
        )

        # Yield lines after a label
        def yield_lines(label: str):
            cursor = get_detail(details_div, label)
            while True:
                cursor = cursor.getnext()

                # If reached end of section
                if cursor is None:
                    break

                if cursor.tag != 'br' and type(cursor) is not HtmlComment:
                    break

                tail_text = cursor.tail.strip() or ''
                if tail_text:
                    yield tail_text

        # Links
        p.add_link(str(self.source), "member detail page")

        # Sources
        p.add_source(self.input.list_url, "member list page")
        p.add_source(str(self.source), "member detail page")

        # TODO: other_names
        # TODO: Track name changes

        # TODO: ids

        # Capitol Office
        p.capitol_office.name = "session contact"
        def process_session_contact():
            lines = list(yield_lines("Session Contact"))
            p.capitol_office.address = format_address(", ".join(lines[:2]))
            lines = lines[2:]
            for line in lines:
                contact_type, number = line.split(": ", 1)
                if contact_type == "Phone":
                    p.capitol_office.voice = number
                elif contact_type == "Fax":
                    p.capitol_office.fax = number
                else:
                    raise ValueError(f"Unknown contact type: {contact_type}")
        process_session_contact()

        # District Office
        p.district_office.name = "interim contact"
        def process_district_contact():
            lines = list(yield_lines("Interim Contact"))
            p.district_office.address = format_address(", ".join(lines[:2]))
            lines = lines[2:]
            for line in lines:
                contact_type, number = line.split(": ", 1)
                if contact_type == "Phone":
                    p.district_office.voice = number
                elif contact_type == "Fax":
                    p.district_office.fax = number
                else:
                    raise ValueError(f"Unknown contact type: {contact_type}")
        process_district_contact()

        # TODO: additional_offices

        # Extras
        p.extras["toll_free_phone"] = get_detail(details_div, "Toll-Free:").tail.strip()
        if leadership_title:
            p.extras["title"] = leadership_title

        return p


class PeopleList(HtmlListPage):
    source = LatestSource()
    selector = CSS("#members tr td:first-child a")

    def process_item(self, item):
        title = item.text_content()
        chamber = title.strip().split(" ", 1)[0]

        if chamber == "Senator":
            chamber = RoleType.UPPER
        elif chamber == "Representative":
            chamber = RoleType.LOWER

        source = re.sub("http://", "https://", item.get("href"))
        input = PartialPerson(chamber=chamber, list_url=str(self.source))

        return PersonDetail(input, source=source)
