import argparse, os, json
import s3fs
from datacite import schema43, DataCiteRESTClient
from caltechdata_api import caltechdata_write, caltechdata_edit

parser = argparse.ArgumentParser(
    description="Adds S3-stored pilot files and a DataCite 4.3 standard json record\
        to CaltechDATA repository"
)
parser.add_argument("folder", nargs=1, help="Folder")
parser.add_argument(
    "json_file", nargs=1, help="file name for json DataCite metadata file"
)

args = parser.parse_args()

# Get access token as environment variable
token = os.environ["TINDTOK"]

endpoint = "https://renc.osn.xsede.org/"

# Get metadata and files from bucket
s3 = s3fs.S3FileSystem(anon=True, client_kwargs={"endpoint_url": endpoint})

# Set up datacite client
password = os.environ["DATACITE"]
prefix = "10.25989"
datacite = DataCiteRESTClient(username="CALTECH.HTE", password=password, prefix=prefix)

path = "ini210004tommorrell/" + args.folder[0] + "/"
dirs = s3.ls(path)
# Strip out reference to top level directory
repeat = dirs.pop(0)
assert repeat == path
#Switch directories to doi
records = []
for record in dirs:
    body = record.split('0_gregoire/')[1]
    records.append(f'{prefix}/{body}')

# We are using the list of unregistered dois
#with open("unregistered_dois.json", "r") as infile:
#    data = json.load(infile)
#records = data["pub"]

abstract = """This record is a component of the Materials Experiment and
Analysis Database (MEAD). It contains raw data and metadata from millions 
of materials synthesis and characterization experiments, as well as the 
analysis and distillation of that data into property and performance 
metrics. The unprecedented quantity and diversity of experimental data 
are searchable by experiment and analysis attributes generated by both 
researchers and data processing software.
"""

with open("completed_dois.json", "r") as infile:
    completed = json.load(infile)

for doi in completed:
    records.remove(doi)

with open("excluded_dois.json", "r") as infile:
    excluded = json.load(infile)

for doi in excluded:
    records.remove(doi)

for record in records:
    base = record.split("/")[1]
    meta_path = path + base + "/" + args.json_file[0]
    metadata = None
    files = s3.ls(path + base)
    if len(files) == 0:
        excluded.append(record)
        print(f"No files available {record}")
        with open("excluded_dois.json", "w") as outfile:
            data = json.dump(excluded, outfile)
    else:
        try:
            metaf = s3.open(meta_path, "rb")
            metadata = json.load(metaf)
        except:
            print(files)
            excluded.append(record)
            print(f"Missing metadata {record}")
            exit()
            with open("excluded_dois.json", "w") as outfile:
                data = json.dump(excluded, outfile)

    if metadata:
        metadata["identifiers"] = [{"identifier": record, "identifierType": "DOI"}]

        # Find the zip file or files
        zipf = s3.glob(path + base + "/*.zip")

        description_string = f"Files available via S3 at {endpoint}{path}<br>"
        for link in zipf:
            fname = link.split("/")[-1]
            link = endpoint + link
            description_string += f"""{fname} <a class="btn btn-xs piwik_download" 
            type="application/octet-stream" href="{link}">
            <i class="fa fa-download"></i> Download</a>    <br>"""

        descr = [
            {"description": description_string, "descriptionType": "Other"},
            {"description": abstract, "descriptionType": "Abstract"},
        ]
        if "descriptions" in metadata:
            metadata["descriptions"] += descr
        else:
            metadata["descriptions"] = descr

        metadata["types"] = {"resourceType": "", "resourceTypeGeneral": "Dataset"}
        metadata["schemaVersion"] = "http://datacite.org/schema/kernel-4"
        metadata["publicationYear"] = str(metadata["publicationYear"])
        metadata["rightsList"] = [
            {
                "rights": "cc-by-sa-4.0",
                "rightsUri": "http://creativecommons.org/licenses/by-sa/4.0/",
            }
        ]
        static = [
            {
                "relatedIdentifier": "10.25989/es8t-kswe",
                "relationType": "IsPartOf",
                "relatedIdentifierType": "DOI",
            },
            {
                "relatedIdentifier": "10.1038/s41524-019-0216-x",
                "relationType": "IsDocumentedBy",
                "relatedIdentifierType": "DOI",
            },
        ]
        if "relatedIdentifiers" in metadata:
            metadata["relatedIdentifiers"] += static
        else:
            metadata["relatedIdentifiers"] = static
        metadata["fundingReferences"] = [
            {
                "funderName": "Office of Science of the U.S. Department of Energy",
                "awardNumber": "DE-SC0004993",
            }
        ]

        for meta in metadata.copy():
            if metadata[meta] == []:
                metadata.pop(meta)
        for contributor in metadata["contributors"]:
            if contributor["affiliation"] == []:
                contributor.pop("affiliation")
        new_cre = []
        for creator in metadata["creators"]:
            if creator["affiliation"] == []:
                creator.pop("affiliation")
            if creator["name"] != "Contributors":
                new_cre.append(creator)
        metadata["creators"] = new_cre

        unnecessary = [
            "id",
            "doi",
            "container",
            "providerId",
            "clientId",
            "agency",
            "state",
        ]
        for un in unnecessary:
            if un in metadata:
                metadata.pop(un)
        if "dates" in metadata:
            for d in metadata["dates"]:
                d["date"] = str(d["date"])
        valid = schema43.validate(metadata)
        if not valid:
            v = schema43.validator.validate(metadata)
            errors = sorted(v.iter_errors(instance), key=lambda e: e.path)
            for error in errors:
                print(error.message)
            exit()

        production = True

        #response = caltechdata_edit("12620", metadata, token, [],[],production, "43")
        response = caltechdata_write(metadata, token, [],production, "43")
        print(response)

        url = response.split("record ")[1].strip()[:-1]

        doi = datacite.update_doi(doi=record, metadata=metadata, url=url)['doi']
        completed.append(doi)
        print(doi)
        with open("completed_dois.json", "w") as outfile:
            data = json.dump(completed, outfile)
